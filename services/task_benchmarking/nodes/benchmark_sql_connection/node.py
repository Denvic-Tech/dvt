import os
import re
from datetime import UTC, datetime
from typing import ClassVar, Literal

from db_connection.connectors.sql import SQLProperties, SQLSecrets
from db_connection.domain import ConnectionRecord

from src.logger import logger
from src.node_dsl import BaseNode, InputField, OutputField, SqlConnectionRecord
from src.node_dsl.runtime.connections import validate_connection_record

DEFAULT_DRIVERS: dict[str, str] = {
    "postgres": "psycopg",
    "clickhouse": "http",
    "mssql": "pyodbc",
    "mysql": "pymysql",
}
DEFAULT_DRIVER_OPTIONS: dict[str, dict] = {
    "mssql": {"driver_name": "ODBC Driver 18 for SQL Server"},
}

_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand_env(value: str) -> str:
    """Expand ``${VAR}`` and ``${VAR:-default}`` references from the process environment.

    ``${VAR:-default}`` uses ``default`` when ``VAR`` is unset or empty (shell semantics).
    ``${VAR}`` without a default fails when ``VAR`` is unset, so a missing benchmark setting
    is reported at this node instead of as an obscure driver error.
    """

    def _replace(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        resolved = os.environ.get(name)
        if default is not None:
            return resolved or default
        if resolved is None:
            raise ValueError(f"Environment variable '{name}' is not set and has no default.")
        return resolved

    return _ENV_REFERENCE.sub(_replace, value)


class BenchmarkSqlConnection(BaseNode):
    """Builds an in-memory SQL connection record for benchmarks without the DVT connection DB."""

    TITLE = "Benchmark SQL Connection"
    CATEGORY = "Benchmark"
    TAGS: ClassVar[list[str]] = ["Testing"]
    VISIBLE = False
    CACHABLE = False

    connection_type: Literal["postgres", "clickhouse", "mssql", "mysql"] = InputField(
        description="Target database type.",
    )
    host: str = InputField(description="Host; supports ${VAR} and ${VAR:-default}.")
    port: int | str = InputField(description="Port; a string supports ${VAR:-default}.")
    database: str = InputField(description="Database name; supports ${VAR:-default}.")
    user: str = InputField(description="User name; supports ${VAR:-default}.")
    password: str | None = InputField(
        default=None,
        description="Password; supports ${VAR:-default}. Used unless password_env resolves.",
    )
    password_env: str | None = InputField(
        default=None,
        description="Environment variable holding the password; takes precedence when it is set.",
    )
    driver: str | None = InputField(
        default=None,
        description="Driver; defaults to psycopg/http/pyodbc/pymysql by connection type.",
    )
    driver_options: dict | None = InputField(
        default=None,
        description="Driver options; mssql defaults to ODBC Driver 18 for SQL Server.",
    )

    connection: SqlConnectionRecord = OutputField()

    def _resolve_password(self) -> str | None:
        if self.password_env:
            from_env = os.environ.get(self.password_env)
            if from_env is not None:
                return from_env
        if self.password is None:
            return None
        return expand_env(self.password)

    def _resolve_port(self) -> int:
        raw = expand_env(self.port) if isinstance(self.port, str) else self.port
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid port for benchmark connection: {raw!r}") from exc

    def build_record(self) -> SqlConnectionRecord:
        connection_type = self.connection_type
        now = datetime.now(UTC)
        driver_options = self.driver_options
        if driver_options is None:
            driver_options = DEFAULT_DRIVER_OPTIONS.get(connection_type)
        properties = SQLProperties(
            host=expand_env(self.host),
            port=self._resolve_port(),
            username=expand_env(self.user),
            database=expand_env(self.database),
        )
        record = ConnectionRecord(
            id=f"benchmark-{self.node_id}",
            name=f"benchmark-{connection_type}",
            kind="sql",
            type=connection_type,
            driver=self.driver or DEFAULT_DRIVERS[connection_type],
            driver_options=driver_options,
            properties=properties.model_dump(),
            secrets=SQLSecrets(password=self._resolve_password()).model_dump(),
            labels={},
            metadata={},
            extra={},
            created_at=now,
            updated_at=now,
        )
        # Fail here, not in the consumer node, when the record is incomplete or inconsistent.
        validate_connection_record(record)
        logger.info(
            "Benchmark connection: type={} driver={} host={} port={} database={} user={}",
            connection_type,
            record.driver,
            properties.host,
            properties.port,
            properties.database,
            properties.username,
        )
        return SqlConnectionRecord(record)

    def process(self) -> None:
        self.connection = self.build_record()
