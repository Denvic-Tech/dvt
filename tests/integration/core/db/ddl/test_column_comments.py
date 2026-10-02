from uuid import uuid4

import dask.dataframe as dd
import pandas as pd
import pytest
import sqlalchemy as sa
from tests.integration.fixtures.db_comments import COMMENT_DIALECTS

from core.db.ddl.column_actions import apply_table_column_actions
from core.db.ddl.column_comments import execute_ddl_sql, mysql_column_definition
from core.db.ddl.models import TableColumnAction
from core.db.ddl.table import (
    create_typed_table_from_columns,
    execute_raw_create_table_sql,
    generate_create_table_ddl_from_columns,
)
from core.db.ddl.table_recreate import recreate_table_safely
from core.db.write_v4 import WriteRequest, WriteTarget, write_dataframe
from core.metadata.db_metadata.comments import normalize_comment
from core.types import DataType, DBColumn

pytest_plugins = ["tests.integration.fixtures.db_comments"]
pytestmark = pytest.mark.docker_required
TEXT = "  Клиент O'Brien; :name 100% \\ путь\nОписание  "


def comments(engine, name):
    return {
        col["name"]: normalize_comment(col.get("comment"))
        for col in sa.inspect(engine).get_columns(name)
    }


@pytest.mark.parametrize("comments_engine", COMMENT_DIALECTS, indirect=True)
def test_existing_column_crud_preserves_data(comments_engine, commented_table):
    engine, table = comments_engine, commented_table
    if engine.dialect.name != "clickhouse":
        sa.Index("dvt_comment_idx_" + uuid4().hex[:10], table.c.value).create(engine)
    before_indexes = sa.inspect(engine).get_indexes(table.name)
    before = sa.inspect(engine).get_columns(table.name)
    before_rows = None
    with engine.connect() as conn:
        before_rows = conn.execute(sa.select(table)).all()
    for value in [TEXT, TEXT, "changed", None, None]:
        action = TableColumnAction(type="set_column_comment", column_name="value", comment=value)
        previous = comments(engine, table.name)["value"]
        preview = apply_table_column_actions(
            engine=engine, table_name=table.name, actions=[action], dry_run=True
        )
        assert comments(engine, table.name)["value"] == previous
        applied = apply_table_column_actions(engine=engine, table_name=table.name, actions=[action])
        assert applied == preview
        if value == previous:
            assert applied[0].sql == []
        assert comments(engine, table.name)["value"] == value
    after = sa.inspect(engine).get_columns(table.name)
    assert sa.inspect(engine).get_indexes(table.name) == before_indexes
    assert [(c["name"], str(c["type"]), c["nullable"], c.get("default")) for c in before] == [
        (c["name"], str(c["type"]), c["nullable"], c.get("default")) for c in after
    ]
    with engine.connect() as conn:
        assert conn.execute(sa.select(table)).all() == before_rows


@pytest.mark.parametrize("comments_engine", COMMENT_DIALECTS, indirect=True)
@pytest.mark.parametrize("raw", [False, True])
def test_typed_and_generated_creation_round_trip(comments_engine, raw):
    engine = comments_engine
    name = "dvt_comment_" + uuid4().hex[:10]
    columns = [
        DBColumn(name="id", dtype=DataType.INT, nullable=False, comment=TEXT),
        DBColumn(name="plain", dtype=DataType.INT, nullable=True),
    ]
    try:
        if raw:
            sql = generate_create_table_ddl_from_columns(
                engine=engine,
                table_name=name,
                columns=columns,
                preserve_input_nullable=True,
            )
            execute_raw_create_table_sql(engine=engine, create_table_sql=sql)
        else:
            create_typed_table_from_columns(engine=engine, table_name=name, columns=columns)
        assert comments(engine, name) == {"id": TEXT, "plain": None}
        action = TableColumnAction(
            type="add_column",
            column_name="added",
            column=DBColumn(name="added", dtype=DataType.INT, nullable=True, comment=TEXT),
        )
        apply_table_column_actions(engine=engine, table_name=name, actions=[action])
        assert comments(engine, name)["added"] == TEXT
        apply_table_column_actions(
            engine=engine,
            table_name=name,
            actions=[
                TableColumnAction(
                    type="recreate_column",
                    column_name="added",
                    column=DBColumn(
                        name="added", dtype=DataType.INT, nullable=True, comment="recreated"
                    ),
                )
            ],
        )
        assert comments(engine, name)["added"] == "recreated"
        recreate_table_safely(engine=engine, table_name=name, columns=columns)
        assert comments(engine, name) == {"id": TEXT, "plain": None}
    finally:
        sa.Table(name, sa.MetaData()).drop(engine, checkfirst=True)


@pytest.mark.parametrize("comments_engine", ["mysql", "mariadb"], indirect=True)
def test_mysql_comment_preserves_vendor_attributes(comments_engine):
    engine = comments_engine
    name = "dvt_attrs_" + uuid4().hex[:10]
    sql = f"""CREATE TABLE `{name}` (
        `id` INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        `value` VARCHAR(42) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT 'a,b',
        `updated` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        `generated` INT GENERATED ALWAYS AS ((id + 1)) VIRTUAL
    )"""
    # A generated expression cannot reference AUTO_INCREMENT on MySQL.
    sql = sql.replace("((id + 1))", "(length(value))")
    try:
        with engine.begin() as conn:
            execute_ddl_sql(conn, sql)
            before = conn.exec_driver_sql(f"SHOW CREATE TABLE `{name}`").one()[1]
        for column in ["id", "value", "updated", "generated"]:
            apply_table_column_actions(
                engine=engine,
                table_name=name,
                actions=[
                    TableColumnAction(type="set_column_comment", column_name=column, comment=TEXT)
                ],
            )
        with engine.connect() as conn:
            after = conn.exec_driver_sql(f"SHOW CREATE TABLE `{name}`").one()[1]
        from core.db.ddl.column_comments import mysql_comment_definition

        for column in ["id", "value", "updated", "generated"]:
            assert mysql_comment_definition(
                mysql_column_definition(before, column), None, engine.dialect
            ) == (
                mysql_comment_definition(
                    mysql_column_definition(after, column), None, engine.dialect
                )
            )
    finally:
        sa.Table(name, sa.MetaData()).drop(engine, checkfirst=True)


@pytest.mark.parametrize("comments_engine", ["postgresql"], indirect=True)
def test_data_write_keeps_existing_column_comments(comments_engine, commented_table):
    before = comments(comments_engine, commented_table.name)
    frame = dd.from_pandas(pd.DataFrame({"id": [3], "value": ["three"]}), npartitions=1)
    write_dataframe(
        frame,
        comments_engine,
        WriteRequest(mode="append", target=WriteTarget(table_name=commented_table.name)),
    )
    assert comments(comments_engine, commented_table.name) == before
    with comments_engine.connect() as connection:
        assert (
            connection.execute(sa.select(sa.func.count()).select_from(commented_table)).scalar()
            == 3
        )
