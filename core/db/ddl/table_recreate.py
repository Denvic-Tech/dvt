from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import sqlalchemy as sa

from core.db.ddl.models import TableCreateSpec
from core.db.ddl.table import create_typed_table_from_columns
from core.types import DBColumn

_ALTER_RENAME_DIALECTS = {"postgresql", "sqlite", "oracle"}
_RENAME_TABLE_DIALECTS = {"mysql", "mariadb", "clickhouse"}
_SUPPORTED_RENAME_DIALECTS = _ALTER_RENAME_DIALECTS | _RENAME_TABLE_DIALECTS | {"mssql"}


class SafeTableRecreateError(RuntimeError):
    """A table replacement failed after the temporary table was validated."""


def normalize_rename_dialect_name(dialect_name: str) -> str:
    name = dialect_name.lower()
    aliases = (
        (("clickhouse",), "clickhouse"),
        (("postgres",), "postgresql"),
        (("mariadb",), "mariadb"),
        (("mysql",), "mysql"),
        (("mssql", "sqlserver"), "mssql"),
        (("oracle",), "oracle"),
        (("sqlite",), "sqlite"),
    )
    for markers, normalized_name in aliases:
        if any(marker in name for marker in markers):
            return normalized_name
    return name


def ensure_table_rename_supported(engine: sa.Engine) -> str:
    dialect_name = normalize_rename_dialect_name(engine.dialect.name or "")
    if dialect_name not in _SUPPORTED_RENAME_DIALECTS:
        raise ValueError(f"Unsupported SQL dialect for table rename: {engine.dialect.name!r}.")
    return dialect_name


def generate_recreate_temp_table_name(
    *,
    table_name: str,
    max_identifier_length: int | None,
    token: str | None = None,
) -> str:
    suffix = f"__dvt_recreate_{token or uuid4().hex[:12]}"
    max_length = max_identifier_length or 128
    if len(suffix) >= max_length:
        return suffix[-max_length:]
    return f"{table_name[: max_length - len(suffix)]}{suffix}"


def _qualified_table_name(
    engine: sa.Engine,
    *,
    table_name: str,
    schema_name: str | None,
) -> str:
    preparer = engine.dialect.identifier_preparer
    quoted_table = preparer.quote(table_name)
    if schema_name:
        return f"{preparer.quote_schema(schema_name)}.{quoted_table}"
    return quoted_table


def build_table_rename_sql(
    engine: sa.Engine,
    *,
    source_table_name: str,
    target_table_name: str,
    schema_name: str | None = None,
) -> str:
    dialect_name = ensure_table_rename_supported(engine)
    qualified_source = _qualified_table_name(
        engine,
        table_name=source_table_name,
        schema_name=schema_name,
    )
    quoted_target = engine.dialect.identifier_preparer.quote(target_table_name)

    if dialect_name in _ALTER_RENAME_DIALECTS:
        return f"ALTER TABLE {qualified_source} RENAME TO {quoted_target}"

    if dialect_name in _RENAME_TABLE_DIALECTS:
        qualified_target = _qualified_table_name(
            engine,
            table_name=target_table_name,
            schema_name=schema_name,
        )
        return f"RENAME TABLE {qualified_source} TO {qualified_target}"

    escaped_source = qualified_source.replace("'", "''")
    escaped_target = target_table_name.replace("'", "''")
    return f"EXEC sp_rename N'{escaped_source}', N'{escaped_target}', N'OBJECT'"


def _drop_table(
    connection: sa.Connection,
    *,
    engine: sa.Engine,
    table_name: str,
    schema_name: str | None,
) -> None:
    qualified_name = _qualified_table_name(
        engine,
        table_name=table_name,
        schema_name=schema_name,
    )
    connection.execute(sa.text(f"DROP TABLE {qualified_name}"))


def _table_exists(
    engine: sa.Engine,
    *,
    table_name: str,
    schema_name: str | None,
) -> bool:
    return sa.inspect(engine).has_table(table_name, schema=schema_name)


def _cleanup_temp_table(
    engine: sa.Engine,
    *,
    table_name: str,
    schema_name: str | None,
) -> None:
    try:
        with engine.begin() as connection:
            if sa.inspect(connection).has_table(table_name, schema=schema_name):
                _drop_table(
                    connection,
                    engine=engine,
                    table_name=table_name,
                    schema_name=schema_name,
                )
    except Exception:
        # Cleanup is best effort and must not hide the original DDL failure.
        pass


def recreate_table_safely(
    *,
    engine: sa.Engine,
    table_name: str,
    columns: list[DBColumn],
    schema_name: str | None = None,
    spec: TableCreateSpec | None = None,
    create_table: Callable[..., sa.Table] = create_typed_table_from_columns,
) -> str:
    """Create and validate a replacement before swapping it with the target."""
    ensure_table_rename_supported(engine)
    temp_table_name = generate_recreate_temp_table_name(
        table_name=table_name,
        max_identifier_length=engine.dialect.max_identifier_length,
    )
    rename_sql = build_table_rename_sql(
        engine,
        source_table_name=temp_table_name,
        target_table_name=table_name,
        schema_name=schema_name,
    )
    recovery_name = _qualified_table_name(
        engine,
        table_name=temp_table_name,
        schema_name=schema_name,
    )

    try:
        create_table(
            engine=engine,
            table_name=temp_table_name,
            columns=columns,
            schema_name=schema_name,
            spec=spec,
        )
        inspector = sa.inspect(engine)
        if not inspector.has_table(temp_table_name, schema=schema_name):
            raise RuntimeError(f"Temporary table {recovery_name} was not created.")

        actual_columns = [
            column["name"] for column in inspector.get_columns(temp_table_name, schema=schema_name)
        ]
        expected_columns = [column.name for column in columns]
        if actual_columns != expected_columns:
            raise RuntimeError(
                f"Temporary table {recovery_name} has columns {actual_columns!r}; "
                f"expected {expected_columns!r}."
            )
    except Exception:
        _cleanup_temp_table(
            engine,
            table_name=temp_table_name,
            schema_name=schema_name,
        )
        raise

    try:
        with engine.begin() as connection:
            if sa.inspect(connection).has_table(table_name, schema=schema_name):
                _drop_table(
                    connection,
                    engine=engine,
                    table_name=table_name,
                    schema_name=schema_name,
                )
            connection.execute(sa.text(rename_sql))
    except Exception as exc:
        try:
            source_exists = _table_exists(
                engine,
                table_name=table_name,
                schema_name=schema_name,
            )
            temp_exists = _table_exists(
                engine,
                table_name=temp_table_name,
                schema_name=schema_name,
            )
        except Exception as inspection_exc:
            raise SafeTableRecreateError(
                "Failed to inspect table state after the replacement error. "
                f"Recovery table may remain at: {recovery_name}. "
                f"Inspection error: {inspection_exc}"
            ) from exc
        if source_exists and temp_exists:
            _cleanup_temp_table(
                engine,
                table_name=temp_table_name,
                schema_name=schema_name,
            )
            raise
        if temp_exists:
            raise SafeTableRecreateError(
                "Failed to rename the temporary table after the source table "
                "was dropped or found absent. "
                f"Recovery table: {recovery_name}."
            ) from exc
        raise SafeTableRecreateError(
            "Failed to replace the source table and no recovery table was found."
        ) from exc

    return temp_table_name
