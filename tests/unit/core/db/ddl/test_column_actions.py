from __future__ import annotations

import pytest
import sqlalchemy as sa

from core.db.ddl import TableColumnAction
from core.db.ddl.column_actions import (
    apply_table_column_actions,
    build_table_column_action_sql,
)
from core.types import DBColumn, DataType


def _column(name: str, dtype: DataType = DataType.STRING, nullable: bool = True) -> DBColumn:
    return DBColumn(name=name, dtype=dtype, nullable=nullable, index=False)


def _engine_with_table() -> sa.Engine:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE items (id INTEGER, old_value TEXT, score TEXT)"))
    return engine


def test_build_table_column_action_sql_builds_add_drop_and_recreate_sql() -> None:
    engine = _engine_with_table()

    applied = build_table_column_action_sql(
        engine=engine,
        table_name="items",
        actions=[
            TableColumnAction(
                type="add_column",
                column_name="new_value",
                column=_column("new_value"),
            ),
            TableColumnAction(type="drop_column", column_name="old_value"),
            TableColumnAction(
                type="recreate_column",
                column_name="score",
                column=_column("score", DataType.FLOAT),
            ),
        ],
    )

    sql = [statement for action in applied for statement in action.sql]

    assert len(sql) == 4
    assert sql[0].startswith("ALTER TABLE items ADD COLUMN")
    assert "new_value" in sql[0]
    assert sql[1] == "ALTER TABLE items DROP COLUMN old_value"
    assert sql[2] == "ALTER TABLE items DROP COLUMN score"
    assert sql[3].startswith("ALTER TABLE items ADD COLUMN")
    assert "score" in sql[3]


def test_apply_table_column_actions_changes_sqlite_table() -> None:
    engine = _engine_with_table()

    apply_table_column_actions(
        engine=engine,
        table_name="items",
        actions=[
            TableColumnAction(
                type="add_column",
                column_name="new_value",
                column=_column("new_value"),
            ),
            TableColumnAction(type="drop_column", column_name="old_value"),
            TableColumnAction(
                type="recreate_column",
                column_name="score",
                column=_column("score", DataType.FLOAT),
            ),
        ],
    )

    columns = {column["name"]: str(column["type"]) for column in sa.inspect(engine).get_columns("items")}

    assert "old_value" not in columns
    assert "new_value" in columns
    assert "score" in columns
    assert "FLOAT" in columns["score"].upper()


def test_apply_table_column_actions_dry_run_does_not_change_table() -> None:
    engine = _engine_with_table()

    applied = apply_table_column_actions(
        engine=engine,
        table_name="items",
        actions=[
            TableColumnAction(
                type="add_column",
                column_name="new_value",
                column=_column("new_value"),
            ),
        ],
        dry_run=True,
    )

    column_names = {column["name"] for column in sa.inspect(engine).get_columns("items")}

    assert applied[0].sql
    assert "new_value" not in column_names


def test_build_table_column_action_sql_rejects_duplicate_column_actions() -> None:
    engine = _engine_with_table()

    with pytest.raises(ValueError, match="Multiple actions"):
        build_table_column_action_sql(
            engine=engine,
            table_name="items",
            actions=[
                TableColumnAction(type="drop_column", column_name="old_value"),
                TableColumnAction(type="drop_column", column_name="OLD_VALUE"),
            ],
        )
