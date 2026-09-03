from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.schema import CreateColumn

from core.db.ddl.models import AppliedTableColumnAction, TableColumnAction
from core.db.ddl.schema import DIALECTS_WITHOUT_SCHEMA_SUPPORT
from core.db.ddl.table import build_typed_table_preview_from_columns
from core.types import DBColumn


def build_table_column_action_sql(
    *,
    engine: sa.Engine,
    table_name: str,
    actions: list[TableColumnAction],
    schema_name: str | None = None,
    database_name: str | None = None,
) -> list[AppliedTableColumnAction]:
    if not actions:
        raise ValueError("actions must not be empty.")

    _validate_no_duplicate_actions(actions)
    effective_schema_name = _resolve_alter_table_schema(
        engine=engine,
        schema_name=schema_name,
        database_name=database_name,
    )
    table = _reflect_table(
        engine=engine,
        table_name=table_name,
        schema_name=effective_schema_name,
    )

    full_table_name = _quote_full_table_name(
        engine=engine,
        table_name=table_name,
        schema_name=effective_schema_name,
    )
    current_column_names = [column.name for column in table.columns]
    applied: list[AppliedTableColumnAction] = []
    for action in actions:
        if action.type == "add_column":
            sql = _build_add_column_action_sql(
                engine=engine,
                full_table_name=full_table_name,
                table_name=table_name,
                schema_name=effective_schema_name,
                action=action,
                current_column_names=current_column_names,
            )
            current_column_names.append(action.column_name)
        elif action.type == "drop_column":
            resolved_column_name = _require_existing_column_name(
                current_column_names,
                action.column_name,
                table_name,
            )
            sql = [
                _build_drop_column_sql(
                    engine=engine,
                    full_table_name=full_table_name,
                    column_name=resolved_column_name,
                )
            ]
            current_column_names = _remove_column_name(current_column_names, resolved_column_name)
        else:
            resolved_column_name = _require_existing_column_name(
                current_column_names,
                action.column_name,
                table_name,
            )
            columns_after_drop = _remove_column_name(current_column_names, resolved_column_name)
            sql = [
                _build_drop_column_sql(
                    engine=engine,
                    full_table_name=full_table_name,
                    column_name=resolved_column_name,
                ),
                *_build_add_column_action_sql(
                    engine=engine,
                    full_table_name=full_table_name,
                    table_name=table_name,
                    schema_name=effective_schema_name,
                    action=action,
                    current_column_names=columns_after_drop,
                ),
            ]
            current_column_names = [*columns_after_drop, action.column_name]

        applied.append(
            AppliedTableColumnAction(
                type=action.type,
                column_name=action.column_name,
                sql=sql,
            )
        )

    return applied


def apply_table_column_actions(
    *,
    engine: sa.Engine,
    table_name: str,
    actions: list[TableColumnAction],
    schema_name: str | None = None,
    database_name: str | None = None,
    dry_run: bool = False,
) -> list[AppliedTableColumnAction]:
    applied = build_table_column_action_sql(
        engine=engine,
        table_name=table_name,
        schema_name=schema_name,
        database_name=database_name,
        actions=actions,
    )
    if dry_run:
        return applied

    with engine.begin() as conn:
        for sql in _flatten_sql(applied):
            conn.execute(sa.text(sql))

    return applied


def _build_add_column_action_sql(
    *,
    engine: sa.Engine,
    full_table_name: str,
    table_name: str,
    schema_name: str | None,
    action: TableColumnAction,
    current_column_names: list[str],
) -> list[str]:
    if _resolve_existing_column_name(current_column_names, action.column_name) is not None:
        raise ValueError(f"Column '{action.column_name}' already exists in table '{table_name}'.")
    if action.column is None:
        raise ValueError(f"column is required for {action.type}.")

    column_sql = _compile_add_column_definition(
        engine=engine,
        table_name=table_name,
        schema_name=schema_name,
        column=action.column,
    )
    return [f"ALTER TABLE {full_table_name} ADD COLUMN {column_sql}"]


def _compile_add_column_definition(
    *,
    engine: sa.Engine,
    table_name: str,
    schema_name: str | None,
    column: DBColumn,
) -> str:
    preview = build_typed_table_preview_from_columns(
        engine=engine,
        table_name=table_name,
        schema_name=schema_name,
        columns=[column],
    )
    sqla_column = next(iter(preview.columns))
    return str(CreateColumn(sqla_column).compile(dialect=engine.dialect)).strip()


def _build_drop_column_sql(
    *,
    engine: sa.Engine,
    full_table_name: str,
    column_name: str,
) -> str:
    quoted_column_name = engine.dialect.identifier_preparer.quote(column_name)
    return f"ALTER TABLE {full_table_name} DROP COLUMN {quoted_column_name}"


def _reflect_table(
    *,
    engine: sa.Engine,
    table_name: str,
    schema_name: str | None,
) -> sa.Table:
    inspector = sa.inspect(engine)
    if not inspector.has_table(table_name, schema=schema_name):
        full_table_name = f"{schema_name}.{table_name}" if schema_name else table_name
        raise ValueError(f"Table '{full_table_name}' does not exist.")
    return sa.Table(
        table_name,
        sa.MetaData(),
        schema=schema_name,
        autoload_with=engine,
    )


def _resolve_alter_table_schema(
    *,
    engine: sa.Engine,
    schema_name: str | None,
    database_name: str | None,
) -> str | None:
    dialect_name = engine.dialect.name.lower()
    if dialect_name == "clickhouse":
        return database_name
    if dialect_name in DIALECTS_WITHOUT_SCHEMA_SUPPORT:
        return None
    return schema_name


def _quote_full_table_name(
    *,
    engine: sa.Engine,
    table_name: str,
    schema_name: str | None,
) -> str:
    preparer = engine.dialect.identifier_preparer
    quoted_table_name = preparer.quote(table_name)
    if not schema_name:
        return quoted_table_name
    return f"{preparer.quote_schema(schema_name)}.{quoted_table_name}"


def _resolve_existing_column_name(
    column_names: list[str],
    requested_column_name: str,
) -> str | None:
    if requested_column_name in column_names:
        return requested_column_name

    lowered = requested_column_name.lower()
    matches = [column_name for column_name in column_names if column_name.lower() == lowered]
    if len(matches) == 1:
        return matches[0]
    return None


def _require_existing_column_name(
    column_names: list[str],
    requested_column_name: str,
    table_name: str,
) -> str:
    resolved_column_name = _resolve_existing_column_name(column_names, requested_column_name)
    if resolved_column_name is None:
        raise ValueError(f"Column '{requested_column_name}' does not exist in table '{table_name}'.")
    return resolved_column_name


def _remove_column_name(column_names: list[str], column_name: str) -> list[str]:
    return [name for name in column_names if name != column_name]


def _validate_no_duplicate_actions(actions: list[TableColumnAction]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for action in actions:
        key = action.column_name.lower()
        if key in seen:
            duplicates.add(action.column_name)
        seen.add(key)
    if duplicates:
        raise ValueError(f"Multiple actions for the same column are not allowed: {sorted(duplicates)!r}.")


def _flatten_sql(applied: list[AppliedTableColumnAction]) -> list[str]:
    return [sql for action in applied for sql in action.sql]
