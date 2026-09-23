from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.dialects import mssql, mysql, oracle, postgresql, sqlite

from core.db.ddl.column_comments import (
    build_column_comment_sql,
    compile_ddl,
    execute_ddl_sql,
    mysql_column_definition,
    mysql_comment_definition,
    separate_create_comment_sql,
    split_ddl_statements,
)
from core.db.ddl.models import TableColumnAction, TableCreateSpec
from core.db.ddl.table import _compile_table_ddl, build_typed_table_preview_from_columns
from core.db.write_v4.column_resolution import resolve_existing_table_write_columns
from core.db.write_v4.models import WriteColumnMapping
from core.types import Column, DataFrameMetadata, DataType, DBColumn


def test_explicit_comment_intent():
    with pytest.raises(ValidationError, match="comment must be provided"):
        TableColumnAction(type="set_column_comment", column_name="id")
    for value in (None, ""):
        assert (
            TableColumnAction(type="set_column_comment", column_name="id", comment=value).comment
            is None
        )
    assert (
        TableColumnAction(type="set_column_comment", column_name="id", comment="  text\n ").comment
        == "  text\n "
    )
    assert "comment" not in WriteColumnMapping.model_fields


@pytest.mark.parametrize("dialect", [postgresql.dialect(), oracle.dialect(), mssql.dialect()])
def test_comment_sql_create_update_delete_and_idempotency(dialect):
    table = sa.Table("Mixed Table", sa.MetaData(), sa.Column("id", sa.Integer))

    def build(comment, current=None):
        return build_column_comment_sql(
            dialect=dialect,
            table=table,
            column=table.c.id,
            comment=comment,
            current_comment=current,
        )

    text = "  Клиент O'Brien; :name 100%\n "
    assert "O''Brien" in build(text)[0]
    assert build(text, text) == []
    assert build(None) == []
    assert len(build(None, text)) == 1
    if dialect.name == "mssql":
        assert "sp_addextendedproperty" in build(text)[0]
        assert "sp_updateextendedproperty" in build(text, "old")[0]
        assert "sp_dropextendedproperty" in build(None, text)[0]


def test_mysql_preserves_exact_server_definition():
    sql = """CREATE TABLE `t` (
  `id` int unsigned NOT NULL AUTO_INCREMENT COMMENT 'old',
  `value` varchar(42) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT 'a,b' COMMENT 'old' INVISIBLE,
  `generated` int GENERATED ALWAYS AS ((`id` + 1)) STORED,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB"""
    definition = mysql_column_definition(sql, "value")
    changed = mysql_comment_definition(definition, "new; O'Brien", mysql.dialect())
    assert changed == definition.replace("COMMENT 'old'", "COMMENT 'new; O''Brien'")
    definition = mysql_column_definition(sql, "generated")
    assert mysql_comment_definition(definition, None, mysql.dialect()) == definition + " COMMENT ''"
    with pytest.raises(ValueError, match="preserve"):
        mysql_column_definition(sql, "absent")


@pytest.mark.parametrize(
    "name", ["postgresql", "mysql", "mariadb", "oracle", "mssql", "clickhouse"]
)
def test_split_preserves_literal_semicolons(name):
    sql = "CREATE TABLE t (id INT); COMMENT ON COLUMN t.id IS 'a; O''Brien :name 100%';"
    assert split_ddl_statements(sql, name) == [
        "CREATE TABLE t (id INT)",
        "COMMENT ON COLUMN t.id IS 'a; O''Brien :name 100%'",
    ]


def test_execution_keeps_colon_and_percent_literal():
    connection = Mock()
    sql = "COMMENT ON COLUMN t.id IS ':name 100%'"
    execute_ddl_sql(connection, sql)
    statement = connection.execute.call_args.args[0]
    assert compile_ddl(statement, postgresql.dialect()) == sql
    assert compile_ddl(statement, mysql.dialect()) == sql


def test_preview_and_resolution_preserve_comments():
    engine = sa.create_mock_engine("postgresql://", lambda *args: None)
    table = build_typed_table_preview_from_columns(
        engine=engine,
        table_name="target",
        columns=[DBColumn(name="id", dtype=DataType.INT, comment="DB comment")],
    )
    sql = _compile_table_ddl(engine=engine, table=table, spec=TableCreateSpec())
    assert "COMMENT ON COLUMN" in sql
    assert "DB comment" in sql
    result = resolve_existing_table_write_columns(
        table=table,
        dataframe_metadata=DataFrameMetadata(
            columns=[
                Column(name="id", dtype=DataType.INT, comment="DF comment"),
                Column(name="extra", dtype=DataType.INT, comment="new comment"),
            ]
        ),
    )
    assert result.columns[0].source_comment == "DF comment"
    assert result.columns[0].db_comment == "DB comment"
    assert result.columns[1].suggested_action.column.comment == "new comment"


def test_unsupported_comments_fail_before_ddl():
    table = sa.Table("t", sa.MetaData(), sa.Column("id", sa.Integer, comment="text"))
    with pytest.raises(ValueError, match="not supported"):
        separate_create_comment_sql(table, sqlite.dialect())


def test_unsupported_typed_resolution_still_returns_readable_df_comment():
    from core.db.write_v4.column_resolution import resolve_typed_create_write_columns

    engine = sa.create_engine("sqlite://")
    result = resolve_typed_create_write_columns(
        engine=engine,
        table_name="target",
        dataframe_metadata=DataFrameMetadata(
            columns=[Column(name="id", dtype=DataType.INT, comment="DF comment")]
        ),
    )
    assert result.columns[0].source_comment == "DF comment"
    assert not result.column_comments_supported
