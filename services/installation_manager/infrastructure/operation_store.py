"""SQLite journal and host-local ownership for one DVT installation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

from ..domain.operation_state import (
    ArtifactKind,
    Checkpoint,
    CheckpointOutcome,
    EventKind,
    FailureReason,
    IdentityConflict,
    IdentityNotEstablished,
    InstanceIdentity,
    InvalidTransition,
    Observation,
    Operation,
    OperationConflict,
    OperationEvent,
    OperationKind,
    OperationNotFound,
    OperationRequest,
    OperationStage,
    OwnerRecord,
    OwnershipConflict,
    ReleasePin,
    transition_allowed,
)
from .operation_files import executor_lock, prepare_database, prepare_directory

STATE_DIR_NAME = ".installation-state"
FORMAT_VERSION = 1
_APPLICATION_ID = 0x44565449  # DVTI
_MAX_PAGE_SIZE = 1000

_SCHEMA = (
    """
    CREATE TABLE identity (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        instance_id TEXT NOT NULL UNIQUE,
        metadata TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE operations (
        admission_order INTEGER PRIMARY KEY,
        id TEXT NOT NULL UNIQUE,
        instance_id TEXT NOT NULL REFERENCES identity(instance_id),
        key_hash TEXT NOT NULL UNIQUE,
        request TEXT NOT NULL,
        stage TEXT NOT NULL,
        admitted_at TEXT NOT NULL,
        stage_started_at TEXT NOT NULL,
        finished_at TEXT,
        owner_claim TEXT,
        owner_acquired_at TEXT,
        observation TEXT NOT NULL,
        CHECK ((owner_claim IS NULL) = (owner_acquired_at IS NULL)),
        CHECK ((stage IN ('succeeded', 'failed', 'cancelled')) = (finished_at IS NOT NULL))
    )
    """,
    """
    CREATE UNIQUE INDEX one_active_operation
    ON operations(instance_id) WHERE finished_at IS NULL
    """,
    """
    CREATE TABLE events (
        cursor INTEGER PRIMARY KEY,
        operation_id TEXT NOT NULL REFERENCES operations(id),
        kind TEXT NOT NULL,
        occurred_at TEXT NOT NULL,
        stage TEXT NOT NULL,
        owner_claim TEXT,
        owner_acquired_at TEXT,
        checkpoint TEXT,
        previous_stage TEXT,
        previous_stage_duration_ms INTEGER
    )
    """,
    "CREATE INDEX operation_event_cursor ON events(operation_id, cursor)",
)


class UnsupportedOperationFormat(RuntimeError):
    """The state on disk cannot be used by this build of the installation manager."""


def _encode(model: InstanceIdentity | OperationRequest | Observation | Checkpoint) -> str:
    return json.dumps(asdict(model), default=str, sort_keys=True, separators=(",", ":"))


def _decode_observation(payload: dict) -> Observation:
    for key in ("staging_id", "backup_id"):
        if payload[key] is not None:
            payload[key] = UUID(payload[key])
    return Observation(**payload)


def _decode_owner(row: sqlite3.Row) -> OwnerRecord | None:
    if row["owner_claim"] is None:
        return None
    return OwnerRecord(UUID(row["owner_claim"]), datetime.fromisoformat(row["owner_acquired_at"]))


def _decode_operation(row: sqlite3.Row) -> Operation:
    payload = json.loads(row["request"])
    payload["kind"] = OperationKind(payload["kind"])
    payload["release"] = ReleasePin(**payload["release"])
    for key in ("bundle_id", "restore_backup_id", "config_id"):
        if payload[key] is not None:
            payload[key] = UUID(payload[key])
    return Operation(
        id=UUID(row["id"]),
        instance_id=UUID(row["instance_id"]),
        request=OperationRequest(**payload),
        stage=OperationStage(row["stage"]),
        admitted_at=datetime.fromisoformat(row["admitted_at"]),
        stage_started_at=datetime.fromisoformat(row["stage_started_at"]),
        finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        last_owner=_decode_owner(row),
        observation=_decode_observation(json.loads(row["observation"])),
    )


def _decode_event(row: sqlite3.Row) -> OperationEvent:
    stage = OperationStage(row["stage"])
    payload = json.loads(row["checkpoint"]) if row["checkpoint"] else None
    checkpoint = None
    if payload is not None:
        checkpoint = Checkpoint(
            stage=stage,
            outcome=CheckpointOutcome(payload["outcome"]),
            reason=FailureReason(payload["reason"]) if payload["reason"] else None,
            observation=_decode_observation(payload["observation"]),
        )
    return OperationEvent(
        cursor=row["cursor"],
        operation_id=UUID(row["operation_id"]),
        kind=EventKind(row["kind"]),
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        stage=stage,
        owner=_decode_owner(row),
        checkpoint=checkpoint,
        previous_stage=OperationStage(row["previous_stage"]) if row["previous_stage"] else None,
        previous_stage_duration_ms=row["previous_stage_duration_ms"],
    )


def _page_size(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= _MAX_PAGE_SIZE:
        raise ValueError(f"Page size must be between 1 and {_MAX_PAGE_SIZE}")


class _OperationOwner:
    """Live capability scoped to the context that holds the OS lock."""

    def __init__(self, store: OperationStore, operation_id: UUID, record: OwnerRecord) -> None:
        self._store = store
        self._operation_id = operation_id
        self._record = record
        self._pid = os.getpid()
        self._closed = False
        self._mutex = Lock()

    @property
    def record(self) -> OwnerRecord:
        return self._record

    def checkpoint(self, checkpoint: Checkpoint) -> Operation:
        if self._pid != os.getpid():
            raise OwnershipConflict("Ownership cannot be inherited by another process")
        with self._mutex:
            if self._closed:
                raise OwnershipConflict("This executor claim is closed")
            return self._store._checkpoint(self._operation_id, self._record, checkpoint)

    def _invalidate(self) -> None:
        with self._mutex:
            self._closed = True


class OperationStore:
    """Use the same protected directory on the same host filesystem for every participant."""

    def __init__(self, state_dir: Path) -> None:
        self._directory = prepare_directory(state_dir)
        self._database = self._directory / "journal.sqlite3"
        self._lock = self._directory / "executor.lock"
        prepare_database(self._database)
        with self._connect(write=True, initialize=True) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS update_route_steps (
                root_id TEXT NOT NULL REFERENCES operations(id),
                position INTEGER NOT NULL, step_id TEXT NOT NULL UNIQUE, request TEXT NOT NULL,
                PRIMARY KEY(root_id, position)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS operator_log (
                cursor INTEGER PRIMARY KEY, operation_id TEXT NOT NULL REFERENCES operations(id),
                at TEXT NOT NULL, message TEXT NOT NULL
            )""")
            db.execute("""CREATE INDEX IF NOT EXISTS operator_log_cursor
                ON operator_log(operation_id, cursor)""")

    @classmethod
    def for_host(cls, data_dir: Path) -> OperationStore:
        """Open the default state directory beneath an existing host data directory."""
        return cls(data_dir / STATE_DIR_NAME)

    @contextmanager
    def _connect(
        self,
        *,
        write: bool = False,
        initialize: bool = False,
    ) -> Iterator[sqlite3.Connection]:
        # An established store must never silently recreate a missing journal.
        with closing(sqlite3.connect(f"{self._database.as_uri()}?mode=rw", uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=EXTRA")
            if db.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise UnsupportedOperationFormat("Installation state requires DELETE journal mode")
            with db:
                db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                self._check_format(db, initialize)
                yield db

    @staticmethod
    def _check_format(db: sqlite3.Connection, initialize: bool) -> None:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        application_id = db.execute("PRAGMA application_id").fetchone()[0]
        if application_id == _APPLICATION_ID and version == FORMAT_VERSION:
            return
        if (
            initialize
            and application_id == version == 0
            and db.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone() is None
        ):
            for stmt in _SCHEMA:
                db.execute(stmt)
            db.execute(f"PRAGMA application_id={_APPLICATION_ID}")
            db.execute(f"PRAGMA user_version={FORMAT_VERSION}")
            return
        raise UnsupportedOperationFormat("Unsupported installation state format")

    def artifact_path(self, kind: ArtifactKind, artifact_id: UUID) -> Path:
        """Resolve an opaque reference. The producing stage owns file creation and protection."""
        if (
            type(kind) is not ArtifactKind
            or not isinstance(artifact_id, UUID)
            or not artifact_id.int
        ):
            raise ValueError("Expected a typed artifact kind and identifier")
        return self._directory / "artifacts" / kind.value / str(artifact_id)

    @staticmethod
    def _identity(db: sqlite3.Connection) -> InstanceIdentity | None:
        row = db.execute(
            "SELECT instance_id, metadata FROM identity WHERE singleton = 1"
        ).fetchone()
        if row is None:
            return None
        metadata = json.loads(row["metadata"])
        return InstanceIdentity(instance_id=UUID(row["instance_id"]), **metadata)

    def identity(self) -> InstanceIdentity | None:
        with self._connect() as db:
            return self._identity(db)

    def establish_identity(self, identity: InstanceIdentity) -> InstanceIdentity:
        if type(identity) is not InstanceIdentity:
            raise ValueError("Expected a typed identity")
        with self._connect(write=True) as db:
            existing = self._identity(db)
            if existing is not None:
                if existing != identity:
                    raise IdentityConflict("The installation already has a different identity")
                return existing
            metadata = json.loads(_encode(identity))
            instance_id = metadata.pop("instance_id")
            db.execute(
                "INSERT INTO identity (singleton, instance_id, metadata) VALUES (1, ?, ?)",
                (instance_id, json.dumps(metadata, separators=(",", ":"))),
            )
            return identity

    @staticmethod
    def _find(db: sqlite3.Connection, operation_id: UUID) -> sqlite3.Row | None:
        return db.execute("SELECT * FROM operations WHERE id = ?", (str(operation_id),)).fetchone()

    @staticmethod
    def _active(db: sqlite3.Connection) -> sqlite3.Row | None:
        return db.execute("SELECT * FROM operations WHERE finished_at IS NULL").fetchone()

    def get(self, operation_id: UUID) -> Operation | None:
        with self._connect() as db:
            row = self._find(db, operation_id)
            return _decode_operation(row) if row is not None else None

    def active(self) -> Operation | None:
        with self._connect() as db:
            row = self._active(db)
            return _decode_operation(row) if row is not None else None

    def history(self, *, before: UUID | None = None, limit: int = 100) -> list[Operation]:
        _page_size(limit)
        with self._connect() as db:
            if before is not None and self._find(db, before) is None:
                raise OperationNotFound("The history cursor is unknown")
            rows = db.execute(
                """
                SELECT * FROM operations
                WHERE ? IS NULL
                    OR admission_order < (SELECT admission_order FROM operations WHERE id = ?)
                ORDER BY admission_order DESC LIMIT ?
                """,
                (str(before) if before is not None else None, str(before), limit),
            )
            return [_decode_operation(row) for row in rows]

    def log_message(self, operation_id: UUID, message: str) -> None:
        """Record a curated progress message, without command output or environment values."""
        with self._connect(write=True) as db:
            db.execute(
                "INSERT INTO operator_log(operation_id, at, message) VALUES (?, ?, ?)",
                (str(operation_id), datetime.now(UTC).isoformat(), message),
            )

    def log_lines(self, operation_id: UUID, *, after: int, limit: int) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT cursor, at, message FROM operator_log WHERE (operation_id = ? OR "
                "operation_id IN (SELECT step_id FROM update_route_steps WHERE root_id = ?)) "
                "AND cursor > ? ORDER BY cursor LIMIT ?", (str(operation_id), str(operation_id), after, limit),
            )
            return [dict(row) for row in rows]

    def events(
        self, operation_id: UUID, *, after: int = 0, limit: int = 100
    ) -> list[OperationEvent]:
        _page_size(limit)
        if type(after) is not int or not 0 <= after < 2**63:
            raise ValueError("Invalid event cursor")
        with self._connect() as db:
            if self._find(db, operation_id) is None:
                raise OperationNotFound("The operation is unknown")
            rows = db.execute(
                """
                SELECT * FROM events WHERE operation_id = ? AND cursor > ?
                ORDER BY cursor LIMIT ?
                """,
                (str(operation_id), after, limit),
            )
            return [_decode_event(row) for row in rows]

    def first_failure(self, operation_id: UUID) -> OperationEvent | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM events
                WHERE operation_id = ? AND json_extract(checkpoint, '$.reason') IS NOT NULL
                ORDER BY cursor LIMIT 1
                """,
                (str(operation_id),),
            ).fetchone()
            return _decode_event(row) if row else None

    def recent_events(self, operation_id: UUID, *, limit: int = 100) -> list[OperationEvent]:
        _page_size(limit)
        with self._connect() as db:
            if self._find(db, operation_id) is None:
                raise OperationNotFound("The operation is unknown")
            rows = db.execute(
                """
                SELECT * FROM events WHERE operation_id = ?
                ORDER BY cursor DESC LIMIT ?
                """,
                (str(operation_id), limit),
            )
            return [_decode_event(row) for row in reversed(rows.fetchall())]

    @staticmethod
    def _key_hash(idempotency_key: str) -> str:
        if not isinstance(idempotency_key, str) or not re.fullmatch(
            r"[!-~]{1,128}", idempotency_key
        ):
            raise ValueError("Expected a bounded opaque idempotency key")
        return hashlib.sha256(idempotency_key.encode("ascii")).hexdigest()

    def by_idempotency_key(self, key: str) -> Operation | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM operations WHERE key_hash = ?", (self._key_hash(key),)
            ).fetchone()
        return _decode_operation(row) if row is not None else None

    def admit(
        self, request: OperationRequest, *, idempotency_key: str, operation_id: UUID | None = None,
        following: tuple[ReleasePin, ...] = (),
    ) -> Operation:
        """Atomically persist a new intent or return the existing intent on exact replay."""
        if type(request) is not OperationRequest:
            raise ValueError("Expected a typed operation request")
        key_hash = self._key_hash(idempotency_key)
        encoded = _encode(request)
        with self._connect(write=True) as db:
            identity = self._identity(db)
            if identity is None:
                raise IdentityNotEstablished("Establish installation identity before admission")
            existing = db.execute(
                "SELECT * FROM operations WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()
            if existing is not None:
                saved = db.execute(
                    "SELECT request FROM update_route_steps WHERE root_id=? AND position>0 ORDER BY position",
                    (existing["id"],),
                ).fetchall()
                pins = tuple(ReleasePin(**json.loads(row[0])["release"]) for row in saved)
                if existing["request"] != encoded or (following and pins != following) or (
                    operation_id is not None and str(operation_id) != existing["id"]
                ):
                    raise OperationConflict(UUID(existing["id"]))
                return _decode_operation(existing)
            active = self._active(db)
            if active is not None:
                raise OperationConflict(UUID(active["id"]))

            operation = self._insert_operation(
                db, operation_id or uuid4(), identity.instance_id, request, key_hash, encoded,
            )
            if following:
                self._save_route(db, operation, following, request.config_id)
            return operation

    def _insert_operation(
        self, db: sqlite3.Connection, operation_id: UUID, instance_id: UUID,
        request: OperationRequest, key_hash: str, encoded: str,
    ) -> Operation:
        now = datetime.now(UTC)
        operation = Operation(
            id=operation_id,
            instance_id=instance_id,
            request=request,
            stage=OperationStage.ADMITTED,
            admitted_at=now,
            stage_started_at=now,
            finished_at=None,
            last_owner=None,
            observation=Observation(),
        )
        db.execute(
            """
            INSERT INTO operations
                (id, instance_id, key_hash, request, stage, admitted_at, stage_started_at,
                 observation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(operation.id),
                str(operation.instance_id),
                key_hash,
                encoded,
                operation.stage,
                now.isoformat(),
                now.isoformat(),
                _encode(operation.observation),
            ),
        )
        self._append_event(db, operation, EventKind.ADMITTED, now)
        return operation

    @staticmethod
    def _save_route(
        db: sqlite3.Connection, root: Operation, following: tuple[ReleasePin, ...],
        config_id: UUID | None,
    ) -> None:
        if root.request.kind is not OperationKind.UPDATE or not config_id:
            raise ValueError("Update routes require a saved configuration")
        requests = [
            OperationRequest(OperationKind.UPDATE, pin, config_id=config_id) for pin in following
        ]
        rows = [(str(root.id), 0, str(root.id), _encode(root.request))]
        rows.extend(
            (str(root.id), position, str(uuid4()), _encode(request))
            for position, request in enumerate(requests, start=1)
        )
        db.executemany(
            "INSERT INTO update_route_steps(root_id, position, step_id, request) VALUES(?,?,?,?)",
            rows,
        )

    def attach_route(self, root_id: UUID, following: tuple[ReleasePin, ...], config_id: UUID) -> None:
        """Commit the continuation before a verified legacy import finishes."""
        if not following:
            return
        with self._connect(write=True) as db:
            saved = db.execute(
                "SELECT request FROM update_route_steps WHERE root_id=? AND position>0 ORDER BY position",
                (str(root_id),),
            ).fetchall()
            if saved:
                if [ReleasePin(**json.loads(row[0])["release"]) for row in saved] != list(following):
                    raise OperationConflict(root_id)
                return
            row = self._find(db, root_id)
            if row is None or row["finished_at"] is not None:
                raise OperationConflict(root_id)
            self._save_route(db, _decode_operation(row), following, config_id)

    def route_target(self, root_id: UUID) -> ReleasePin | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT request FROM update_route_steps WHERE root_id=? ORDER BY position DESC LIMIT 1",
                (str(root_id),),
            ).fetchone()
            return ReleasePin(**json.loads(row["request"])["release"]) if row else None

    def route_root(self, step_id: UUID) -> UUID:
        with self._connect() as db:
            row = db.execute(
                "SELECT root_id FROM update_route_steps WHERE step_id=?", (str(step_id),),
            ).fetchone()
            return UUID(row[0]) if row else step_id

    def current_step(self, root_id: UUID) -> Operation | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT o.* FROM update_route_steps s JOIN operations o ON o.id=s.step_id "
                "WHERE s.root_id=? ORDER BY s.position DESC LIMIT 1", (str(root_id),),
            ).fetchone()
            if row is None:
                row = self._find(db, root_id)
            return _decode_operation(row) if row else None

    def _advance_route(self, db: sqlite3.Connection, finished: Operation) -> None:
        row = db.execute(
            "SELECT next.step_id, next.request FROM update_route_steps current "
            "JOIN update_route_steps next ON next.root_id=current.root_id "
            "AND next.position=current.position+1 WHERE current.step_id=?",
            (str(finished.id),),
        ).fetchone()
        if row is not None:
            payload = json.loads(row["request"])
            request = OperationRequest(
                OperationKind.UPDATE, ReleasePin(**payload["release"]), config_id=UUID(payload["config_id"]),
            )
            self._insert_operation(
                db, UUID(row["step_id"]), finished.instance_id, request,
                "route:" + row["step_id"], row["request"],
            )

    def executor_busy(self) -> bool:
        try:
            with executor_lock(self._lock):
                return False
        except OwnershipConflict:
            return True

    @contextmanager
    def claim(self, operation_id: UUID) -> Iterator[_OperationOwner]:
        """Try to acquire the instance lock for the active operation; keep it until context exit."""
        with executor_lock(self._lock):
            with self._connect(write=True) as db:
                row = self._find(db, operation_id)
                if row is None:
                    raise OperationNotFound("The operation is unknown")
                operation = _decode_operation(row)
                if operation.stage.terminal:
                    raise OwnershipConflict("The operation has already finished")
                record = OwnerRecord(uuid4(), datetime.now(UTC))
                db.execute(
                    "UPDATE operations SET owner_claim = ?, owner_acquired_at = ? WHERE id = ?",
                    (str(record.claim_id), record.claimed_at.isoformat(), str(operation_id)),
                )
                self._append_event(
                    db,
                    replace(operation, last_owner=record),
                    EventKind.OWNER_ACQUIRED,
                    record.claimed_at,
                )
            owner = _OperationOwner(self, operation_id, record)
            try:
                yield owner
            finally:
                owner._invalidate()

    def _checkpoint(
        self,
        operation_id: UUID,
        record: OwnerRecord,
        checkpoint: Checkpoint,
    ) -> Operation:
        if type(checkpoint) is not Checkpoint:
            raise ValueError("Expected a typed checkpoint")
        with self._connect(write=True) as db:
            row = self._find(db, operation_id)
            if row is None or _decode_owner(row) != record:
                raise OwnershipConflict("The executor claim is no longer current")
            previous = _decode_operation(row)
            stage = checkpoint.stage
            if not transition_allowed(previous, checkpoint):
                raise InvalidTransition(f"Cannot move from {previous.stage} to {stage}")

            now = datetime.now(UTC)
            changes = {
                field.name: value
                for field in fields(checkpoint.observation)
                if (value := getattr(checkpoint.observation, field.name)) is not None
            }
            moved_stage = stage != previous.stage
            operation = replace(
                previous,
                stage=stage,
                stage_started_at=now if moved_stage else previous.stage_started_at,
                finished_at=now if stage.terminal else None,
                observation=replace(previous.observation, **changes),
            )
            db.execute(
                """
                UPDATE operations SET stage = ?, stage_started_at = ?, finished_at = ?,
                    observation = ? WHERE id = ?
                """,
                (
                    stage,
                    operation.stage_started_at.isoformat(),
                    operation.finished_at.isoformat() if operation.finished_at else None,
                    _encode(operation.observation),
                    str(operation_id),
                ),
            )
            self._append_event(
                db,
                operation,
                EventKind.CHECKPOINT,
                now,
                checkpoint=checkpoint,
                previous=previous if moved_stage else None,
            )
            if stage is OperationStage.SUCCEEDED:
                self._advance_route(db, operation)
            return operation

    @staticmethod
    def _append_event(
        db: sqlite3.Connection,
        operation: Operation,
        kind: EventKind,
        occurred_at: datetime,
        *,
        checkpoint: Checkpoint | None = None,
        previous: Operation | None = None,
    ) -> None:
        labels = {
            OperationStage.ADMITTED: "Запрос принят",
            OperationStage.PREPARING: "Подготовка комплекта",
            OperationStage.PREPARED: "Комплект проверен",
            OperationStage.MAINTENANCE: "Начало обслуживания",
            OperationStage.BACKUP: "Создание резервной копии",
            OperationStage.MIGRATING: "Настройка базы данных",
            OperationStage.APPLYING: "Запуск сервисов",
            OperationStage.VERIFYING: "Проверка доступности",
            OperationStage.RESUMING: "Завершение операции",
            OperationStage.SUCCEEDED: "Операция завершена",
            OperationStage.CANCELLED: "Операция отменена",
            OperationStage.FAILED: "Операция завершилась ошибкой",
            OperationStage.RECOVERING: "Восстановление",
            OperationStage.RECOVERY_REQUIRED: "Требуется восстановление",
        }
        if kind is not EventKind.OWNER_ACQUIRED:
            message = labels[operation.stage]
            if checkpoint and checkpoint.reason:
                message += f" ({checkpoint.reason.value})"
            db.execute(
                "INSERT INTO operator_log(operation_id, at, message) VALUES (?, ?, ?)",
                (str(operation.id), occurred_at.isoformat(), message),
            )
        owner = operation.last_owner
        duration_ms = None
        if previous is not None:
            duration_ms = max(
                0, int((occurred_at - previous.stage_started_at).total_seconds() * 1000)
            )
        db.execute(
            """
            INSERT INTO events
                (operation_id, kind, occurred_at, stage, owner_claim, owner_acquired_at, checkpoint,
                 previous_stage, previous_stage_duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(operation.id),
                kind,
                occurred_at.isoformat(),
                operation.stage,
                str(owner.claim_id) if owner else None,
                owner.claimed_at.isoformat() if owner else None,
                _encode(checkpoint) if checkpoint else None,
                previous.stage if previous else None,
                duration_ms,
            ),
        )
