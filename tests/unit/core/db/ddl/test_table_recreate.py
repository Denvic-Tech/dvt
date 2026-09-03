from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mssql, mysql, oracle, postgresql, sqlite

import core.db.ddl.table_recreate as subject
from core.types import DataType, DBColumn


def _engine_for(dialect) -> Mock:
    engine = Mock()
    engine.dialect = dialect
    return engine


@pytest.mark.parametrize(
    ("dialect", "expected"),
    [
        (
            postgresql.dialect(),
            'ALTER TABLE "some schema"."temp table" RENAME TO "target table"',
        ),
        (
            sqlite.dialect(),
            'ALTER TABLE "some schema"."temp table" RENAME TO "target table"',
        ),
        (
            oracle.dialect(),
            'ALTER TABLE "some schema"."temp table" RENAME TO "target table"',
        ),
        (
            mysql.dialect(),
            "RENAME TABLE `some schema`.`temp table` TO `some schema`.`target table`",
        ),
        (
            mssql.dialect(),
            "EXEC sp_rename N'[some schema].[temp table]', N'target table', N'OBJECT'",
        ),
    ],
)
def test_build_table_rename_sql(dialect, expected):
    assert (
        subject.build_table_rename_sql(
            _engine_for(dialect),
            source_table_name="temp table",
            target_table_name="target table",
            schema_name="some schema",
        )
        == expected
    )


def test_build_clickhouse_rename_sql():
    dialect = mysql.dialect()
    dialect.name = "clickhouse"

    assert (
        subject.build_table_rename_sql(
            _engine_for(dialect),
            source_table_name="tmp",
            target_table_name="target",
            schema_name="db",
        )
        == "RENAME TABLE db.tmp TO db.target"
    )


def test_temp_name_respects_identifier_limit():
    name = subject.generate_recreate_temp_table_name(
        table_name="x" * 200,
        max_identifier_length=63,
        token="123456789abc",
    )

    assert len(name) == 63
    assert name.endswith("__dvt_recreate_123456789abc")


def test_pre_swap_failure_cleans_temp_and_preserves_source():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE items (old_value TEXT)"))

    def failing_create(**kwargs):
        with kwargs["engine"].begin() as connection:
            connection.execute(sa.text(f'CREATE TABLE "{kwargs["table_name"]}" (new_value TEXT)'))
        raise RuntimeError("index failed")

    with pytest.raises(RuntimeError, match="index failed"):
        subject.recreate_table_safely(
            engine=engine,
            table_name="items",
            columns=[
                DBColumn(
                    name="new_value",
                    dtype=DataType.STRING,
                    nullable=True,
                    index=False,
                )
            ],
            create_table=failing_create,
        )

    inspector = sa.inspect(engine)
    assert inspector.has_table("items")
    assert inspector.get_table_names() == ["items"]
    assert [column["name"] for column in inspector.get_columns("items")] == ["old_value"]


def test_post_drop_rename_failure_reports_recovery_table(monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE items (old_value TEXT)"))

    monkeypatch.setattr(
        subject,
        "build_table_rename_sql",
        lambda *args, **kwargs: "INVALID RENAME SQL",
    )
    monkeypatch.setattr(
        subject,
        "_table_exists",
        Mock(side_effect=[False, True]),
    )

    with pytest.raises(
        subject.SafeTableRecreateError,
        match=r"Recovery table: .*__dvt_recreate_",
    ):
        subject.recreate_table_safely(
            engine=engine,
            table_name="items",
            columns=[
                DBColumn(
                    name="new_value",
                    dtype=DataType.STRING,
                    nullable=True,
                    index=False,
                )
            ],
        )


def test_post_drop_inspection_failure_keeps_recovery_name(monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE items (old_value TEXT)"))

    monkeypatch.setattr(
        subject,
        "build_table_rename_sql",
        lambda *args, **kwargs: "INVALID RENAME SQL",
    )
    monkeypatch.setattr(
        subject,
        "_table_exists",
        Mock(side_effect=RuntimeError("inspection unavailable")),
    )

    with pytest.raises(
        subject.SafeTableRecreateError,
        match=r"Recovery table may remain at: .*__dvt_recreate_.*inspection unavailable",
    ):
        subject.recreate_table_safely(
            engine=engine,
            table_name="items",
            columns=[
                DBColumn(
                    name="new_value",
                    dtype=DataType.STRING,
                    nullable=True,
                    index=False,
                )
            ],
        )


def test_unsupported_dialect_fails_before_create():
    engine = sa.create_engine("sqlite://")
    engine.dialect.name = "unsupported"
    create_table = Mock()

    with pytest.raises(ValueError, match="Unsupported SQL dialect"):
        subject.recreate_table_safely(
            engine=engine,
            table_name="items",
            columns=[],
            create_table=create_table,
        )

    create_table.assert_not_called()
