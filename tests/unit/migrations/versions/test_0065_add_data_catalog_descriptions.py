import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

base_migration = importlib.import_module("migrations.versions.0064_add_data_catalog_tables")
migration = importlib.import_module("migrations.versions.0065_add_data_catalog_descriptions")

NEW_COLUMNS = {
    "datasets": {
        "description_updated_by",
        "description_updated_at",
        "observed_at_run",
        "last_check_error",
        "last_check_error_kind",
    },
    "dataset_fields": {"description_updated_by", "description_updated_at"},
}


def _database():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    sa.Table("organizations", metadata, sa.Column("id", sa.String, primary_key=True))
    sa.Table(
        "projects",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("organization_id", sa.String, nullable=False),
        sa.UniqueConstraint("id", "organization_id"),
    )
    metadata.create_all(engine)
    _run(engine, base_migration.upgrade)
    return engine


def _run(engine, operation):
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            operation()


def _columns(engine, table) -> set[str]:
    return {item["name"] for item in sa.inspect(engine).get_columns(table)}


def test_upgrade_is_idempotent_and_downgrade_removes_only_new_columns():
    engine = _database()
    before = {table: _columns(engine, table) for table in NEW_COLUMNS}

    _run(engine, migration.upgrade)
    _run(engine, migration.upgrade)
    for table, names in NEW_COLUMNS.items():
        assert names <= _columns(engine, table)

    _run(engine, migration.downgrade)
    for table in NEW_COLUMNS:
        assert _columns(engine, table) == before[table]
    assert "datasets" in sa.inspect(engine).get_table_names()

    _run(engine, migration.upgrade)
    for table, names in NEW_COLUMNS.items():
        assert names <= _columns(engine, table)
