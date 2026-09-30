from contextlib import contextmanager
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from clickhouse_sqlalchemy import types as ch_types
from clickhouse_sqlalchemy.drivers.http.base import ClickHouseDialect_http
from pydantic import ValidationError
from sqlalchemy.dialects import mssql, mysql, oracle, postgresql, sqlite

from core.db.ddl import column_actions
from core.db.ddl.column_nullable import (
    build_column_nullable_sql,
    clickhouse_nullable_type,
    mysql_nullable_definition,
    mysql_strict_mode,
)
from core.db.ddl.models import TableColumnAction
from core.metadata.db_metadata.nullable import reflected_column_nullable


def nullable_action(value=False, name="value"):
    return TableColumnAction(type="set_column_nullable", column_name=name, nullable=value)


@pytest.mark.parametrize("payload", [
    {}, {"nullable": None}, {"nullable": "false"}, {"nullable": "true"},
    {"nullable": 0}, {"nullable": 1}, {"nullable": False, "column": None},
    {"nullable": True, "comment": None},
])
def test_nullable_requires_boolean_and_no_column_or_comment(payload):
    with pytest.raises(ValidationError):
        TableColumnAction(type="set_column_nullable", column_name="value", **payload)


def test_nullable_contract_preserves_false_and_rejects_misplaced_flag():
    assert nullable_action(False).nullable is False
    assert nullable_action(True).nullable is True
    with pytest.raises(ValidationError, match="only for"):
        TableColumnAction(type="drop_column", column_name="value", nullable=False)


@pytest.mark.parametrize("dialect,fragment", [
    (postgresql.dialect(), "ALTER COLUMN"),
    (oracle.dialect(), "MODIFY ("),
    (mssql.dialect(), "ALTER COLUMN"),
    (mysql.dialect(), "MODIFY COLUMN"),
    (ClickHouseDialect_http(), "MODIFY COLUMN"),
])
@pytest.mark.parametrize("nullable", [False, True])
def test_native_sql_and_noop(dialect, fragment, nullable):
    table = sa.Table(
        "Mixed% Table", sa.MetaData(),
        sa.Column("Mixed% value", sa.Numeric(18, 7), nullable=not nullable), schema="Mixed Schema",
    )
    column = next(iter(table.c))
    kwargs = {
        "dialect": dialect, "table": table, "column": column, "nullable": nullable,
        "mysql_definition": "`Mixed% value` decimal(18,7) NULL DEFAULT NULL COMMENT 'x'",
        "clickhouse_definition": {"type": "Decimal(18, 7)", "default_kind": ""},
    }
    sql = build_column_nullable_sql(**kwargs)[0]
    assert fragment in sql and "Mixed% Table" in sql and "Mixed% value" in sql
    assert "Mixed Schema" in sql and "%%" not in sql
    if dialect.name == "mssql":
        assert "NUMERIC(18, 7)" in sql
    column.nullable = nullable
    assert build_column_nullable_sql(**kwargs) == []


def test_mssql_preserves_collation_and_max_length():
    table = sa.Table("t", sa.MetaData(), sa.Column(
        "v", mssql.NVARCHAR(None, collation="Latin1_General_100_BIN2"), nullable=True,
    ))
    sql = build_column_nullable_sql(
        dialect=mssql.dialect(), table=table, column=table.c.v, nullable=False,
    )[0]
    assert "NVARCHAR(max) COLLATE Latin1_General_100_BIN2 NOT NULL" in sql


def test_sqlite_rejected_even_for_noop():
    table = sa.Table("t", sa.MetaData(), sa.Column("v", sa.Integer, nullable=True))
    with pytest.raises(ValueError, match="not supported"):
        build_column_nullable_sql(
            dialect=sqlite.dialect(), table=table, column=table.c.v, nullable=True,
        )


@pytest.mark.parametrize("definition", [
    "`v` int unsigned NOT NULL AUTO_INCREMENT COMMENT 'NULL DEFAULT NULL'",
    "`v` varchar(42) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL DEFAULT 'NULL' COMMENT 'x'",
    "`v` timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)",
    "`v` int NOT NULL DEFAULT (if(1, NULL, 0)) COMMENT 'NOT NULL' INVISIBLE",
])
def test_mysql_only_replaces_nullability(definition):
    changed = mysql_nullable_definition(definition, True)
    assert changed == definition.replace(" NOT NULL ", " NULL ", 1)
    assert mysql_nullable_definition(changed, False) == definition


def test_mysql_removes_only_top_level_default_null():
    definition = "`v` varchar(20) DEFAULT NULL COMMENT 'DEFAULT NULL; :name 100%'"
    changed = mysql_nullable_definition(definition, False)
    assert "COMMENT 'DEFAULT NULL; :name 100%'" in changed
    assert changed.endswith(" NOT NULL")
    assert changed.count("DEFAULT NULL") == 1


@pytest.mark.parametrize("original,changed", [
    ("String", "Nullable(String)"),
    ("Nullable(String)", "Nullable(String)"),
    ("LowCardinality(String)", "LowCardinality(Nullable(String))"),
    ("LowCardinality(Nullable(String))", "LowCardinality(Nullable(String))"),
    ("DateTime64(6, 'Europe/Moscow')", "Nullable(DateTime64(6, 'Europe/Moscow'))"),
    ("Enum8('NULL' = 1, 'a,b' = 2)", "Nullable(Enum8('NULL' = 1, 'a,b' = 2))"),
])
def test_clickhouse_preserves_exact_native_type(original, changed):
    assert clickhouse_nullable_type(original, True) == changed
    expected = original.replace("Nullable(", "", 1)
    if "Nullable(" in original:
        expected = expected[:-1]
    assert clickhouse_nullable_type(changed, False) == expected


@pytest.mark.parametrize("original", ["Array(Nullable(Int32))", "Tuple(Int32)", "Map(String, Int32)"])
def test_clickhouse_rejects_unsupported_nullable_types(original):
    with pytest.raises(ValueError, match="not supported"):
        clickhouse_nullable_type(original, True)


@pytest.mark.parametrize("column_type,expected", [
    (ch_types.String(), False),
    (ch_types.Nullable(ch_types.String()), True),
    (ch_types.LowCardinality(ch_types.Nullable(ch_types.String())), True),
    (ch_types.Array(ch_types.Nullable(ch_types.Int32())), False),
])
def test_clickhouse_reflection_nullability(column_type, expected):
    assert reflected_column_nullable({"type": column_type, "nullable": False}, "clickhouse") == expected


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("comment", ["new; :name 100%", None])
def test_mysql_combined_actions_preserve_previous_change(monkeypatch, reverse, comment):
    engine = Mock(dialect=mysql.dialect())
    table = sa.Table(
        "t", sa.MetaData(), sa.Column("value", sa.String(42), nullable=True, comment="old"),
    )
    monkeypatch.setattr(column_actions, "_reflect_table", lambda **kw: table)
    connection = Mock()
    engine.connect.return_value.__enter__ = Mock(return_value=connection)
    engine.connect.return_value.__exit__ = Mock(return_value=False)
    connection.execute.return_value.one.return_value = (
        "t", "CREATE TABLE `t` (`value` varchar(42) DEFAULT NULL COMMENT 'old')",
    )
    actions = [
        nullable_action(),
        TableColumnAction(type="set_column_comment", column_name="value", comment=comment),
    ]
    if reverse:
        actions.reverse()
    result = column_actions.build_table_column_action_sql(engine=engine, table_name="t", actions=actions)
    assert [item.type for item in result] == [action.type for action in actions]
    assert all(len(item.sql) == 1 for item in result)
    final = result[-1].sql[0]
    assert "NOT NULL" in final and "DEFAULT NULL" not in final
    assert "COMMENT '" + (comment or "") + "'" in final
    assert "varchar(42)" in final


@pytest.mark.parametrize("other", [
    TableColumnAction(type="drop_column", column_name="VALUE"),
    nullable_action(True, "VALUE"),
])
def test_conflicting_actions_fail_before_reflection(monkeypatch, other):
    reflect = Mock(side_effect=AssertionError("must not reflect invalid batch"))
    monkeypatch.setattr(column_actions, "_reflect_table", reflect)
    with pytest.raises(ValueError, match="Multiple actions"):
        column_actions.build_table_column_action_sql(
            engine=Mock(), table_name="t", actions=[nullable_action(), other],
        )


def test_missing_column_rejected():
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE t (value INT)")
        with pytest.raises(ValueError, match="does not exist"):
            column_actions.build_table_column_action_sql(
                engine=engine, table_name="t", actions=[nullable_action(name="absent")],
            )
    finally:
        engine.dispose()


def test_preflight_checks_whole_batch_before_any_ddl(monkeypatch):
    # SQLite supplies real data for the preflight; stub only unsupported DDL generation.
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE t (value INT, untouched INT)")
        connection.exec_driver_sql("INSERT INTO t VALUES (NULL, 42)")
    actions = [TableColumnAction(type="drop_column", column_name="untouched"), nullable_action()]
    from core.db.ddl.models import AppliedTableColumnAction
    planned = [
        AppliedTableColumnAction(type=action.type, column_name=action.column_name, sql=[sql])
        for action, sql in zip(actions, [
            "ALTER TABLE t DROP COLUMN untouched", "ALTER TABLE t ALTER COLUMN value SET NOT NULL",
        ], strict=True)
    ]
    monkeypatch.setattr(column_actions, "build_table_column_action_sql", lambda **kw: planned)
    try:
        assert column_actions.apply_table_column_actions(
            engine=engine, table_name="t", actions=actions, dry_run=True,
        ) == planned
        with pytest.raises(ValueError, match=r"value.*contains NULL"):
            column_actions.apply_table_column_actions(engine=engine, table_name="t", actions=actions)
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT * FROM t").all() == [(None, 42)]
    finally:
        engine.dispose()


@pytest.mark.parametrize("fails", [False, True])
def test_mysql_strict_mode_restored_after_success_or_failure(fails):
    connection = Mock()
    connection.execute.return_value.scalar_one.return_value = "NO_ENGINE_SUBSTITUTION"
    @contextmanager
    def expected_result():
        if fails:
            with pytest.raises(ValueError, match="DDL failed"):
                yield
        else:
            yield
    with expected_result(), mysql_strict_mode(connection, enabled=True):
        if fails:
            raise ValueError("DDL failed")
    modes = [call.args[1]["mode"] for call in connection.execute.call_args_list[1:]]
    assert modes == ["NO_ENGINE_SUBSTITUTION,STRICT_ALL_TABLES", "NO_ENGINE_SUBSTITUTION"]


@pytest.mark.parametrize("info", [{"identity": {}}, {"autoincrement": True}, {"computed": {"sqltext": "1"}}])
def test_generated_column_cannot_silently_ignore_nullable(info):
    table = sa.Table("t", sa.MetaData(), sa.Column("v", sa.Integer, nullable=False, info=info))
    with pytest.raises(ValueError, match="generated column"):
        build_column_nullable_sql(
            dialect=mysql.dialect(), table=table, column=table.c.v, nullable=True,
            mysql_definition="`v` int NOT NULL AUTO_INCREMENT",
        )
