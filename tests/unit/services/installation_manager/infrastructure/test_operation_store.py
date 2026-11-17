from __future__ import annotations

import os
import sqlite3
import stat
import subprocess
import sys
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from services.installation_manager.domain.operation_state import (
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
    OperationConflict,
    OperationKind,
    OperationRequest,
    OperationStage,
    OwnershipConflict,
    ReleasePin,
)
from services.installation_manager.infrastructure.operation_store import (
    FORMAT_VERSION,
    STATE_DIR_NAME,
    OperationStore,
    UnsupportedOperationFormat,
)

_MANIFEST = "sha256:" + "a" * 64
_SOURCE = "sha256:" + "b" * 64
_TARGET = "sha256:" + "c" * 64
_SEPARATE_PROCESS = """
import sys
from pathlib import Path
from uuid import UUID

from services.installation_manager.domain.operation_state import (
    Checkpoint, OperationConflict, OperationKind, OperationRequest, OperationStage, ReleasePin,
)
from services.installation_manager.infrastructure.operation_store import OperationStore

data_dir, command, argument = sys.argv[1:]
store = OperationStore.for_host(Path(data_dir))
if command == "admit":
    request = OperationRequest(OperationKind.UPDATE, ReleasePin("dvt-1.25.0", "sha256:" + "a"*64))
    print("ready", flush=True)
    if not sys.stdin.readline():
        raise SystemExit(1)
    try:
        print("admitted", store.admit(request, idempotency_key=argument).id, flush=True)
    except OperationConflict as err:
        print("conflict", err.operation_id, flush=True)
else:
    operation_id = UUID(argument)
    with store.claim(operation_id) as owner:
        if command == "hold":
            operation = owner.checkpoint(Checkpoint(OperationStage.PREPARING))
            print("held", operation.stage, owner.record.claim_id, flush=True)
            sys.stdin.readline()
        else:
            previous = store.get(operation_id)
            operation = owner.checkpoint(Checkpoint(OperationStage.CANCELLED))
            print("recovered", previous.stage, operation.stage, owner.record.claim_id, flush=True)
"""


def _identity() -> InstanceIdentity:
    return InstanceIdentity(uuid4(), "/var/lib/dvt", "dvt", "127.0.0.1", 8888, "https://dvt.test")


def _request() -> OperationRequest:
    return OperationRequest(OperationKind.UPDATE, ReleasePin("dvt-1.25.0", _MANIFEST))


def _start_child(data_dir: Path, command: str, argument: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", _SEPARATE_PROCESS, str(data_dir), command, argument],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )


@pytest.fixture
def store(tmp_path: Path) -> OperationStore:
    store = OperationStore.for_host(tmp_path)
    store.establish_identity(_identity())
    return store


def test_identity_is_immutable_and_equal_replay_does_not_write(tmp_path):
    store = OperationStore.for_host(tmp_path)
    with pytest.raises(IdentityNotEstablished):
        store.admit(_request(), idempotency_key="first")
    identity = _identity()
    assert store.establish_identity(identity) == identity

    database = tmp_path / STATE_DIR_NAME / "journal.sqlite3"
    original = database.read_bytes()
    original_mtime = database.stat().st_mtime_ns
    reopened = OperationStore.for_host(tmp_path)
    assert (
        reopened.establish_identity(replace(identity, public_url="HTTPS://DVT.TEST:443/"))
        == identity
    )
    for incompatible in (
        replace(identity, instance_id=uuid4()),
        replace(identity, data_dir="/var/lib/other"),
        replace(identity, compose_project="dvt-other"),
        replace(identity, manager_address="127.0.0.2"),
        replace(identity, manager_port=8889),
        replace(identity, public_url="http://dvt.test"),
    ):
        with pytest.raises(IdentityConflict):
            reopened.establish_identity(incompatible)
    assert reopened.identity() == identity
    assert database.read_bytes() == original
    assert database.stat().st_mtime_ns == original_mtime


def test_admission_replay_conflicts_and_bounded_history(store):
    config_id, bundle_id, backup_id = uuid4(), uuid4(), uuid4()
    request = replace(
        _request(),
        config_id=config_id,
        bundle_id=bundle_id,
        restore_backup_id=backup_id,
        ai_mcp_enabled=False,
        task_workers_count=2,
        app_port=8080,
    )
    operation = store.admit(request, idempotency_key="first")
    assert operation.instance_id == store.identity().instance_id
    assert operation.last_owner is None
    assert store.active() == operation
    for incompatible in (
        replace(request, config_id=uuid4()),
        replace(request, ai_mcp_enabled=True),
        replace(request, release=ReleasePin(request.release.release_id, _TARGET)),
    ):
        with pytest.raises(OperationConflict) as error:
            store.admit(incompatible, idempotency_key="first")
        assert error.value.operation_id == operation.id
    with pytest.raises(OperationConflict) as error:
        store.admit(request, idempotency_key="next")
    assert error.value.operation_id == operation.id
    assert store.get(operation.id) == operation
    assert len(store.events(operation.id)) == 1
    assert store.artifact_path(ArtifactKind.CONFIG, config_id).parts[-3:] == (
        "artifacts",
        "config",
        str(config_id),
    )

    with store.claim(operation.id) as owner:
        finished = owner.checkpoint(Checkpoint(OperationStage.CANCELLED))
    assert store.active() is None
    next_op = store.admit(request, idempotency_key="next")
    assert next_op.id != operation.id
    assert store.admit(request, idempotency_key="first") == finished
    assert store.history(limit=1) == [next_op]
    assert store.history(before=next_op.id, limit=1) == [finished]
    assert store.history(before=finished.id) == []


def test_checkpoint_observations_page_and_stale_claim(store):
    operation = store.admit(_request(), idempotency_key="first")
    staging_id, backup_id = uuid4(), uuid4()
    with store.claim(operation.id) as stale:
        assert store.active().last_owner == stale.record
        with pytest.raises(InvalidTransition):
            stale.checkpoint(Checkpoint(OperationStage.MIGRATING))
        stale.checkpoint(
            Checkpoint(
                OperationStage.PREPARING,
                observation=Observation(
                    source_digest=_SOURCE,
                    target_digest=_TARGET,
                    staging_id=staging_id,
                    source_revision="0062",
                    target_revision="0069",
                ),
            )
        )
        stale.checkpoint(
            Checkpoint(
                OperationStage.PREPARING,
                CheckpointOutcome.RETRYABLE_ERROR,
                FailureReason.TLS,
            )
        )

    with store.claim(operation.id) as current:
        assert current.record.claim_id != stale.record.claim_id
        with pytest.raises(OwnershipConflict):
            stale.checkpoint(Checkpoint(OperationStage.CANCELLED))
        current.checkpoint(
            Checkpoint(
                OperationStage.PREPARED,
                CheckpointOutcome.VERIFIED,
            )
        )
        current.checkpoint(Checkpoint(OperationStage.MAINTENANCE))
        with pytest.raises(InvalidTransition):
            current.checkpoint(Checkpoint(OperationStage.CANCELLED))
        current.checkpoint(
            Checkpoint(
                OperationStage.BACKUP,
                observation=Observation(
                    backup_id=backup_id,
                ),
            )
        )
        current.checkpoint(Checkpoint(OperationStage.MIGRATING))
        with pytest.raises(InvalidTransition):
            current.checkpoint(Checkpoint(OperationStage.FAILED))
        current.checkpoint(
            Checkpoint(
                OperationStage.RECOVERY_REQUIRED,
                CheckpointOutcome.BLOCKED,
                FailureReason.MIGRATION,
            )
        )
        current.checkpoint(Checkpoint(OperationStage.RECOVERING))
        with pytest.raises(InvalidTransition):
            current.checkpoint(Checkpoint(OperationStage.FAILED))
        current.checkpoint(
            Checkpoint(
                OperationStage.RECOVERY_REQUIRED,
                CheckpointOutcome.BLOCKED,
                FailureReason.BACKUP,
            )
        )
        with pytest.raises(OperationConflict) as conflict:
            store.admit(_request(), idempotency_key="another")
        assert conflict.value.operation_id == operation.id
        current.checkpoint(Checkpoint(OperationStage.RECOVERING))
        current.checkpoint(Checkpoint(OperationStage.APPLYING))
        current.checkpoint(Checkpoint(OperationStage.VERIFYING))
        current.checkpoint(Checkpoint(OperationStage.RESUMING))
        finished = current.checkpoint(
            Checkpoint(
                OperationStage.SUCCEEDED,
                CheckpointOutcome.VERIFIED,
                observation=Observation(observed_digest=_TARGET, observed_revision="0069"),
            )
        )
        with pytest.raises(InvalidTransition):
            current.checkpoint(Checkpoint(OperationStage.SUCCEEDED, CheckpointOutcome.VERIFIED))
    with pytest.raises(OwnershipConflict), store.claim(operation.id):
        pytest.fail("A finished operation must have no executor")

    assert finished.observation == Observation(
        source_digest=_SOURCE,
        target_digest=_TARGET,
        observed_digest=_TARGET,
        source_revision="0062",
        target_revision="0069",
        observed_revision="0069",
        staging_id=staging_id,
        backup_id=backup_id,
    )
    assert store.get(operation.id) == finished
    assert finished.finished_at == finished.stage_started_at
    first = store.events(operation.id, limit=3)
    tail = store.events(operation.id, after=first[-1].cursor)
    assert [event.kind for event in first] == [
        EventKind.ADMITTED,
        EventKind.OWNER_ACQUIRED,
        EventKind.CHECKPOINT,
    ]
    assert first[-1].previous_stage is OperationStage.ADMITTED
    assert first[-1].previous_stage_duration_ms >= 0
    assert tail[0].checkpoint.reason is FailureReason.TLS
    assert tail[1].owner == current.record
    assert tail[-1].stage is OperationStage.SUCCEEDED
    assert store.events(operation.id, after=tail[-1].cursor) == []
    with pytest.raises(ValueError):
        store.events(operation.id, limit=1001)


@pytest.mark.parametrize(
    ("stages", "target", "prior_backup"),
    [
        ((OperationStage.PREPARED,), OperationStage.MIGRATING, False),
        ((OperationStage.PREPARED,), OperationStage.MIGRATING, True),
        ((OperationStage.PREPARED,), OperationStage.RECOVERING, False),
        (
            (OperationStage.PREPARED, OperationStage.MAINTENANCE, OperationStage.BACKUP),
            OperationStage.MIGRATING,
            False,
        ),
        (
            (
                OperationStage.PREPARED,
                OperationStage.MAINTENANCE,
                OperationStage.RECOVERY_REQUIRED,
                OperationStage.RECOVERING,
            ),
            OperationStage.MIGRATING,
            False,
        ),
    ],
)
def test_update_rejects_migration_or_recovery_shortcuts(store, stages, target, prior_backup):
    operation = store.admit(_request(), idempotency_key="update")
    backup_id = uuid4()
    with store.claim(operation.id) as owner:
        owner.checkpoint(Checkpoint(OperationStage.PREPARING))
        for stage in stages:
            owner.checkpoint(Checkpoint(stage))
        if prior_backup:
            owner.checkpoint(Checkpoint(stages[-1], observation=Observation(backup_id=backup_id)))
        before = store.get(operation.id)
        events_before = store.events(operation.id)

        for observation in (Observation(), Observation(backup_id=backup_id)):
            with pytest.raises(InvalidTransition):
                owner.checkpoint(Checkpoint(target, observation=observation))
            assert store.active() == before
            assert store.events(operation.id) == events_before


def test_install_can_migrate_from_prepared_without_backup(store):
    request = replace(_request(), kind=OperationKind.INSTALL)
    operation = store.admit(request, idempotency_key="install")
    with store.claim(operation.id) as owner:
        owner.checkpoint(Checkpoint(OperationStage.PREPARING))
        owner.checkpoint(Checkpoint(OperationStage.PREPARED))
        migrating = owner.checkpoint(Checkpoint(OperationStage.MIGRATING))
    assert migrating.stage is OperationStage.MIGRATING
    assert migrating.observation.backup_id is None


@pytest.mark.parametrize("kind", [OperationKind.MANAGER_RECOVERY, OperationKind.RESTORE])
def test_dedicated_recovery_can_start_from_prepared(store, kind):
    operation = store.admit(replace(_request(), kind=kind), idempotency_key="recovery")
    with store.claim(operation.id) as owner:
        owner.checkpoint(Checkpoint(OperationStage.PREPARING))
        owner.checkpoint(Checkpoint(OperationStage.PREPARED))
        recovering = owner.checkpoint(Checkpoint(OperationStage.RECOVERING))
    assert recovering.stage is OperationStage.RECOVERING


def test_update_can_migrate_and_resume_with_committed_backup(store, tmp_path):
    operation = store.admit(_request(), idempotency_key="update")
    backup_id = uuid4()
    with store.claim(operation.id) as owner:
        owner.checkpoint(Checkpoint(OperationStage.PREPARING))
        owner.checkpoint(Checkpoint(OperationStage.PREPARED))
        owner.checkpoint(Checkpoint(OperationStage.MAINTENANCE))
        owner.checkpoint(Checkpoint(OperationStage.BACKUP))
        backed_up = owner.checkpoint(
            Checkpoint(
                OperationStage.BACKUP,
                CheckpointOutcome.VERIFIED,
                observation=Observation(backup_id=backup_id),
            )
        )
        events_before = store.events(operation.id)
        with pytest.raises(InvalidTransition):
            owner.checkpoint(
                Checkpoint(
                    OperationStage.MIGRATING,
                    observation=Observation(backup_id=uuid4()),
                )
            )
        assert store.active() == backed_up
        assert store.events(operation.id) == events_before
        migrating = owner.checkpoint(Checkpoint(OperationStage.MIGRATING))
        assert migrating.observation.backup_id == backup_id
        owner.checkpoint(
            Checkpoint(
                OperationStage.RECOVERY_REQUIRED,
                CheckpointOutcome.BLOCKED,
                FailureReason.MIGRATION,
            )
        )

    reopened = OperationStore.for_host(tmp_path)
    with reopened.claim(operation.id) as owner:
        owner.checkpoint(Checkpoint(OperationStage.RECOVERING))
        resumed = owner.checkpoint(Checkpoint(OperationStage.MIGRATING))
    assert resumed.stage is OperationStage.MIGRATING
    assert resumed.observation.backup_id == backup_id


@pytest.mark.parametrize("keys", [("same", "same"), ("first", "second")])
def test_concurrent_admission_from_independent_processes(store, tmp_path, keys):
    with (
        _start_child(tmp_path, "admit", keys[0]) as first,
        _start_child(tmp_path, "admit", keys[1]) as second,
    ):
        try:
            for process in (first, second):
                assert process.stdout.readline().strip() == "ready"
            for process in (first, second):
                process.stdin.write("\n")
                process.stdin.flush()
            lines = []
            for process in (first, second):
                output, error = process.communicate(timeout=15)
                assert process.returncode == 0, error
                lines.append(output.split())
        finally:
            for process in (first, second):
                if process.poll() is None:
                    process.kill()

    expected = ["admitted", "admitted" if keys[0] == keys[1] else "conflict"]
    assert sorted(status for status, _ in lines) == expected
    assert len({operation_id for _, operation_id in lines}) == 1
    operation = store.active()
    assert str(operation.id) == lines[0][1]
    assert operation.request == _request()
    assert operation.instance_id == store.identity().instance_id
    assert store.history() == [operation]
    assert [event.kind for event in store.events(operation.id)] == [EventKind.ADMITTED]


def test_exclusive_owner_reopens_journal_after_process_death(store, tmp_path):
    operation = store.admit(_request(), idempotency_key="first")
    with _start_child(tmp_path, "hold", str(operation.id)) as first:
        try:
            held = first.stdout.readline().split()
            assert held[:2] == ["held", "preparing"]
            checkpoint = store.get(operation.id)
            assert checkpoint.stage is OperationStage.PREPARING
            assert str(checkpoint.last_owner.claim_id) == held[2]
            with pytest.raises(OwnershipConflict), store.claim(operation.id):
                pytest.fail("Only one process may hold the instance lock")

            other_dir = tmp_path / "other"
            other_dir.mkdir()
            other = OperationStore.for_host(other_dir)
            other_identity = replace(
                _identity(), data_dir="/var/lib/other", compose_project="other"
            )
            other.establish_identity(other_identity)
            other_op = other.admit(_request(), idempotency_key="first")
            with other.claim(other_op.id) as owner:
                assert owner.checkpoint(Checkpoint(OperationStage.CANCELLED)).instance_id == (
                    other_identity.instance_id
                )
        finally:
            if first.poll() is None:
                first.kill()
            first.communicate(timeout=15)
    assert first.returncode != 0

    with _start_child(tmp_path, "recover", str(operation.id)) as second:
        output, error = second.communicate(timeout=15)
        assert second.returncode == 0, error
    recovered = output.split()
    assert recovered[:3] == ["recovered", "preparing", "cancelled"]
    assert recovered[3] != held[2]
    reopened = OperationStore.for_host(tmp_path)
    (finished,) = reopened.history()
    assert reopened.active() is None
    assert finished.id == operation.id
    assert str(finished.last_owner.claim_id) == recovered[3]
    assert [event.kind for event in reopened.events(finished.id)] == [
        EventKind.ADMITTED,
        EventKind.OWNER_ACQUIRED,
        EventKind.CHECKPOINT,
        EventKind.OWNER_ACQUIRED,
        EventKind.CHECKPOINT,
    ]


def test_version_and_structured_secret_boundary(store, tmp_path):
    witness = "synthetic-secret-for-this-test-only"
    with pytest.raises(ValueError, match="public HTTP"):
        replace(_identity(), public_url=f"https://operator:{witness}@dvt.test")
    with pytest.raises(ValueError, match="public HTTP"):
        replace(_identity(), public_url=f"https://dvt.test?secret={witness}")
    with pytest.raises(ValueError, match="revision"):
        Observation(observed_revision=witness)
    with pytest.raises(ValueError, match="failure reason"):
        Checkpoint(OperationStage.ADMITTED, CheckpointOutcome.BLOCKED, reason=witness)
    with pytest.raises(TypeError):
        store.admit({"password": witness}, idempotency_key=witness, raw_output=witness)

    operation = store.admit(_request(), idempotency_key=witness)
    with store.claim(operation.id) as owner, pytest.raises(ValueError, match="typed checkpoint"):
        owner.checkpoint({"stdout": witness})
    database = tmp_path / STATE_DIR_NAME / "journal.sqlite3"
    assert witness.encode() not in database.read_bytes()

    with closing(sqlite3.connect(database)) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (FORMAT_VERSION,)
        db.execute(f"PRAGMA user_version={FORMAT_VERSION + 1}")
    unsupported_bytes = database.read_bytes()
    for read in (store.identity, lambda: OperationStore.for_host(tmp_path)):
        with pytest.raises(UnsupportedOperationFormat):
            read()
    assert database.read_bytes() == unsupported_bytes


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux ownership and mode bits")
def test_linux_files_are_private_and_insecure_existing_files_are_rejected(store, tmp_path):
    operation = store.admit(_request(), idempotency_key="first")
    with store.claim(operation.id):
        directory = tmp_path / STATE_DIR_NAME
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert directory.stat().st_uid == os.geteuid()
        for path in directory.iterdir():
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            assert path.stat().st_uid == os.geteuid()

        # Inspect the actual rollback journal while it exists.
        database = directory / "journal.sqlite3"
        with closing(sqlite3.connect(database)) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE operations SET observation='{}'")
            rollback = directory / "journal.sqlite3-journal"
            assert stat.S_IMODE(rollback.stat().st_mode) == 0o600
            assert rollback.stat().st_uid == os.geteuid()
            db.rollback()

    database.chmod(0o644)
    with pytest.raises(PermissionError):
        OperationStore.for_host(tmp_path)
    assert stat.S_IMODE(database.stat().st_mode) == 0o644
    database.chmod(0o600)
    directory.chmod(0o755)
    with pytest.raises(PermissionError):
        OperationStore.for_host(tmp_path)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o755


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux symlink and hardlink checks"
)
def test_linux_symlink_or_hardlink_cannot_select_another_journal(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    other_store = OperationStore.for_host(other)
    other_identity = _identity()
    other_store.establish_identity(other_identity)
    other_state = other / STATE_DIR_NAME
    candidate = tmp_path / STATE_DIR_NAME
    candidate.symlink_to(other_state, target_is_directory=True)
    with pytest.raises(PermissionError):
        OperationStore.for_host(tmp_path)
    candidate.unlink()
    candidate.mkdir(mode=0o700)

    database = candidate / "journal.sqlite3"
    database.symlink_to(other_state / database.name)
    with pytest.raises(OSError):
        OperationStore.for_host(tmp_path)
    database.unlink()

    database.hardlink_to(other_state / database.name)
    with pytest.raises(PermissionError):
        OperationStore.for_host(tmp_path)
    database.unlink()
    assert other_store.identity() == other_identity
