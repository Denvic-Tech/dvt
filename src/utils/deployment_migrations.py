"""Database proof shared by the standalone migrator and application startup."""

import json
import os
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Connection, bindparam, text

CONTEXT_ENV = "DVT_MIGRATION_CONTEXT"
DATABASE_ID_SQL = """
SELECT (pg_control_system()).system_identifier::text || ':' || oid::text
FROM pg_database WHERE datname = current_database()
"""
RECEIPTS = "dvt_release_control.migration_receipts"
CREATE_RECEIPTS = f"""
CREATE TABLE IF NOT EXISTS {RECEIPTS} (
    operation_id uuid PRIMARY KEY,
    context jsonb NOT NULL,
    phase text NOT NULL CHECK (phase IN ('core', 'done', 'resumed'))
)
"""


@dataclass(frozen=True)
class MigrationContext:
    operation_id: UUID
    source: str | None
    target: str
    database: str
    required_extensions: tuple[str, ...]
    encoded: str

    @classmethod
    def read(cls) -> "MigrationContext | None":
        encoded = os.environ.get(CONTEXT_ENV, "")
        if not encoded:
            return None
        value = json.loads(encoded)
        operation_id = UUID(value["operation"])
        UUID(value["instance"])
        if (
            set(value)
            != {
                "operation",
                "instance",
                "manifest",
                "image",
                "database",
                "source",
                "target",
                "required_extensions",
            }
            or any(
                not re.fullmatch(r"sha256:[0-9a-f]{64}", value[k]) for k in ("manifest", "image")
            )
            or not re.fullmatch(r"[0-9]+:[0-9]+", value["database"])
            or not re.fullmatch(r"[0-9a-f]{4,32}", value["target"])
            or (
                value["source"] is not None and not re.fullmatch(r"[0-9a-f]{4,32}", value["source"])
            )
            or not isinstance(value["required_extensions"], list)
            or any(
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name)
                for name in value["required_extensions"]
            )
        ):
            raise ValueError("Invalid deployment migration context")
        return cls(
            operation_id,
            value["source"],
            value["target"],
            value["database"],
            tuple(value["required_extensions"]),
            encoded,
        )

    def assert_database(self, connection: Connection) -> None:
        if connection.execute(text(DATABASE_ID_SQL)).scalar_one() != self.database:
            raise RuntimeError("The migration context belongs to a different PostgreSQL database")

    def phase(self, connection: Connection) -> str | None:
        self.assert_database(connection)
        if (
            connection.execute(text("SELECT to_regclass(:name)"), {"name": RECEIPTS}).scalar_one()
            is None
        ):
            return None
        receipt = connection.execute(
            text(f"""
                SELECT phase, context = CAST(:context AS jsonb)
                FROM {RECEIPTS} WHERE operation_id = :operation
            """),
            {"context": self.encoded, "operation": self.operation_id},
        ).one_or_none()
        if receipt is not None and not receipt[1]:
            raise RuntimeError("The existing migration receipt belongs to another deployment")
        return receipt[0] if receipt else None

    def assert_extensions(self, connection: Connection) -> None:
        if not self.required_extensions:
            return
        query = text("""
            SELECT name FROM extensions
            WHERE name IN :names AND is_installed AND is_enabled
              AND upper(deps_status::text) = 'READY' AND error_message IS NULL
        """).bindparams(bindparam("names", expanding=True))
        ready = set(connection.execute(query, {"names": self.required_extensions}).scalars())
        if ready != set(self.required_extensions):
            raise RuntimeError("Required extensions are unavailable")

    def assert_frozen(self, connection: Connection) -> None:
        if (
            self.source is not None
            and not connection.execute(
                text("""
                SELECT true FROM task_admission_control
                WHERE singleton = 1 AND frozen AND operation_id = :operation
            """),
                {"operation": self.operation_id},
            ).scalar_one_or_none()
        ):
            raise RuntimeError("The update does not own the frozen task admission gate")

    def assert_ready(self, connection: Connection, target: str) -> None:
        phase = self.phase(connection)
        if target != self.target or phase not in {"done", "resumed"}:
            raise RuntimeError("No successful migration receipt for this release and database")
        if phase == "done":
            self.assert_frozen(connection)
        self.assert_extensions(connection)
