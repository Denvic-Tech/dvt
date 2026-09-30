from uuid import uuid4

import pytest
import sqlalchemy as sa
from clickhouse_sqlalchemy import Table as ClickHouseTable, engines, types as ch_types
from tests.integration.fixtures.db_comments import COMMENT_DIALECTS

from core.db.ddl.column_actions import apply_table_column_actions
from core.db.ddl.column_comments import execute_ddl_sql, mysql_column_definition
from core.db.ddl.models import TableColumnAction
from core.metadata.db_metadata import load_db_table_metadata

pytest_plugins = ["tests.integration.fixtures.db_comments"]
pytestmark = pytest.mark.docker_required


def action(nullable, column="value"):
    return TableColumnAction(type="set_column_nullable", column_name=column, nullable=nullable)


def metadata(engine, table):
    return {c.name: c for c in load_db_table_metadata(engine, table_name=table.name).columns}


@pytest.fixture
def nullable_table(comments_engine):
    engine = comments_engine
    name = "nullable_" + uuid4().hex[:10]
    if engine.dialect.name == "clickhouse":
        table = ClickHouseTable(
            name, sa.MetaData(),
            sa.Column("id", ch_types.Int32()),
            sa.Column("value", ch_types.Nullable(ch_types.String()),
                      server_default=sa.text("'seed'"), comment="old"),
            engines.MergeTree(order_by="id"),
        )
    else:
        table = sa.Table(
            name, sa.MetaData(),
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
            sa.Column("value", sa.String(42), nullable=True,
                      server_default=sa.text("'seed'"), comment="old"),
        )
    table.create(engine)
    try:
        if engine.dialect.name != "clickhouse":
            indexed_column = table.c.id if engine.dialect.name == "mssql" else table.c.value
            sa.Index("idx_" + uuid4().hex[:10], indexed_column).create(engine)
        with engine.begin() as connection:
            connection.execute(table.insert(), [{"id": 1, "value": "one"}, {"id": 2, "value": "two"}])
        yield table
    finally:
        table.drop(engine, checkfirst=True)


@pytest.mark.parametrize("comments_engine", COMMENT_DIALECTS, indirect=True)
@pytest.mark.parametrize("reverse", [False, True])
def test_nullable_and_comment_roundtrip_preserves_data_and_attributes(
    comments_engine, nullable_table, reverse,
):
    engine, table = comments_engine, nullable_table
    before_columns = sa.inspect(engine).get_columns(table.name)
    before_indexes = sa.inspect(engine).get_indexes(table.name)
    before_pk = sa.inspect(engine).get_pk_constraint(table.name)
    for nullable, comment in [(False, "new; :name 100%"), (True, None)]:
        actions = [
            action(nullable),
            TableColumnAction(type="set_column_comment", column_name="value", comment=comment),
        ]
        if reverse:
            actions.reverse()
        preview = apply_table_column_actions(
            engine=engine, table_name=table.name, actions=actions, dry_run=True,
        )
        assert metadata(engine, table)["value"].nullable is not nullable
        applied = apply_table_column_actions(engine=engine, table_name=table.name, actions=actions)
        assert applied == preview
        column = metadata(engine, table)["value"]
        assert column.nullable is nullable and column.comment == comment
        assert apply_table_column_actions(
            engine=engine, table_name=table.name, actions=[action(nullable)],
        )[0].sql == []
        with engine.connect() as connection:
            assert connection.execute(sa.select(table).order_by(table.c.id)).all() == [
                (1, "one"), (2, "two"),
            ]
    after_columns = sa.inspect(engine).get_columns(table.name)
    assert [(c["name"], str(c["type"]), c.get("default")) for c in before_columns] == [
        (c["name"], str(c["type"]), c.get("default")) for c in after_columns
    ]
    assert sa.inspect(engine).get_indexes(table.name) == before_indexes
    assert sa.inspect(engine).get_pk_constraint(table.name) == before_pk


@pytest.mark.parametrize("comments_engine", COMMENT_DIALECTS, indirect=True)
def test_null_data_rejects_entire_batch(comments_engine, nullable_table):
    engine, table = comments_engine, nullable_table
    with engine.begin() as connection:
        connection.execute(table.insert(), {"id": 3, "value": None})
    actions = [
        TableColumnAction(type="set_column_comment", column_name="id", comment="must not apply"),
        action(False),
    ]
    assert apply_table_column_actions(
        engine=engine, table_name=table.name, actions=actions, dry_run=True,
    )
    with pytest.raises(ValueError, match=r"value.*contains NULL"):
        apply_table_column_actions(engine=engine, table_name=table.name, actions=actions)
    assert metadata(engine, table)["value"].nullable is True
    assert metadata(engine, table)["id"].comment is None
    with engine.connect() as connection:
        assert connection.execute(sa.select(table.c.value).where(table.c.id == 3)).scalar() is None


@pytest.mark.parametrize("comments_engine", COMMENT_DIALECTS[:-1], indirect=True)
def test_primary_key_cannot_be_made_nullable(comments_engine, nullable_table):
    with pytest.raises(ValueError, match="Primary key"):
        apply_table_column_actions(
            engine=comments_engine, table_name=nullable_table.name, actions=[action(True, "id")],
        )
    assert metadata(comments_engine, nullable_table)["id"].nullable is False


@pytest.mark.parametrize("comments_engine", ["mysql", "mariadb"], indirect=True)
def test_mysql_preserves_attributes_and_restores_nonstrict_mode(comments_engine):
    engine = comments_engine
    name = "nullable_attrs_" + uuid4().hex[:10]
    with engine.begin() as connection:
        execute_ddl_sql(connection, f"""CREATE TABLE `{name}` (
            `value` VARCHAR(42) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin
                NULL DEFAULT NULL COMMENT 'NULL :name 100%',
            `updated` TIMESTAMP(6) NULL DEFAULT CURRENT_TIMESTAMP(6)
                ON UPDATE CURRENT_TIMESTAMP(6)
        )""")
        connection.execute(sa.text(f"INSERT INTO `{name}` (value) VALUES ('one')"))
    try:
        # A dedicated pool guarantees that the action and assertion use the same session.
        bound_engine = sa.create_engine(engine.url, poolclass=sa.pool.StaticPool)
        try:
            with bound_engine.begin() as connection:
                connection.exec_driver_sql("SET SESSION sql_mode = ''")
                before = connection.exec_driver_sql(f"SHOW CREATE TABLE `{name}`").one()[1]
            before_columns = sa.inspect(bound_engine).get_columns(name)
            apply_table_column_actions(
                engine=bound_engine, table_name=name, actions=[action(False), action(False, "updated")],
            )
            with bound_engine.connect() as connection:
                after = connection.exec_driver_sql(f"SHOW CREATE TABLE `{name}`").one()[1]
                assert connection.exec_driver_sql("SELECT @@SESSION.sql_mode").scalar_one() == ""
            after_columns = sa.inspect(bound_engine).get_columns(name)
            for old, new in zip(before_columns, after_columns, strict=True):
                assert not new["nullable"]
                assert str(old["type"]) == str(new["type"])
                assert getattr(old["type"], "collation", None) == getattr(new["type"], "collation", None)
                assert old["comment"] == new["comment"]
                if old["name"] == "updated":
                    assert old["default"] == new["default"]
                else:
                    assert new["default"] is None
            # The timestamp's precision and ON UPDATE expression must survive verbatim.
            assert mysql_column_definition(after, "updated") == (
                mysql_column_definition(before, "updated").replace(" NULL ", " NOT NULL ", 1)
            )
        finally:
            bound_engine.dispose()
    finally:
        sa.Table(name, sa.MetaData()).drop(engine, checkfirst=True)


@pytest.mark.parametrize("comments_engine", ["clickhouse"], indirect=True)
def test_clickhouse_low_cardinality_metadata_roundtrip(comments_engine):
    engine = comments_engine
    name = "nullable_lc_" + uuid4().hex[:10]
    with engine.begin() as connection:
        execute_ddl_sql(connection, f"""CREATE TABLE {name} (
            id Int32, value LowCardinality(Nullable(String)) DEFAULT 'seed' COMMENT 'old'
        ) ENGINE = MergeTree ORDER BY id""")
        connection.exec_driver_sql(f"INSERT INTO {name} VALUES (1, 'one')")
    table = sa.Table(name, sa.MetaData())
    try:
        from core.metadata.db_metadata.dialects.clickhouse import load_clickhouse_metadata
        for nullable in [True, False, True]:
            apply_table_column_actions(engine=engine, table_name=name, actions=[action(nullable)])
            assert metadata(engine, table)["value"].nullable is nullable
            catalog = load_clickhouse_metadata(engine)
            matching = [t for t in catalog.iter_tables() if t.name == name]
            assert next(c for c in matching[0].columns if c.name == "value").nullable is nullable
            with engine.connect() as connection:
                row = connection.exec_driver_sql(f"DESCRIBE TABLE {name}").mappings().all()[1]
                expected = "LowCardinality(Nullable(String))" if nullable else "LowCardinality(String)"
                assert row["type"] == expected
                assert row["default_expression"] == "'seed'" and row["comment"] == "old"
                assert connection.exec_driver_sql(f"SELECT value FROM {name}").scalar() == "one"
    finally:
        table.drop(engine, checkfirst=True)


@pytest.mark.parametrize("comments_engine", COMMENT_DIALECTS, indirect=True)
def test_gateway_returns_updated_nullable_metadata(comments_engine, nullable_table, monkeypatch):
    from services.gateway.routes.utils.DDL import table as route

    from src.schemas.http.create_table import ApplyTableColumnActionsRequest

    monkeypatch.setattr(route, "build_engine_from_connection_string", lambda **kw: comments_engine)
    request = ApplyTableColumnActionsRequest(
        connection_id="test", table_name=nullable_table.name,
        actions=[action(False)], dry_run=True,
    )
    preview = route._apply_table_column_actions_request(request, "unused")
    assert preview.table_metadata is None and preview.sql
    request.dry_run = False
    result = route._apply_table_column_actions_request(request, "unused")
    assert result.success and result.sql == preview.sql
    assert next(c for c in result.table_metadata.columns if c.name == "value").nullable is False


@pytest.mark.parametrize("comments_engine", ["mssql"], indirect=True)
def test_mssql_dependent_index_is_not_removed(comments_engine, nullable_table):
    engine, table = comments_engine, nullable_table
    sa.Index("dependent_" + uuid4().hex[:10], table.c.value).create(engine)
    indexes = sa.inspect(engine).get_indexes(table.name)
    with pytest.raises(sa.exc.DBAPIError, match="dependent"):
        apply_table_column_actions(engine=engine, table_name=table.name, actions=[action(False)])
    assert sa.inspect(engine).get_indexes(table.name) == indexes
    assert metadata(engine, table)["value"].nullable is True
    with engine.connect() as connection:
        assert connection.execute(sa.select(table).order_by(table.c.id)).all() == [
            (1, "one"), (2, "two"),
        ]
