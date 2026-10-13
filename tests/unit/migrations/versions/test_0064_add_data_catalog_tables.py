import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

migration = importlib.import_module("migrations.versions.0064_add_data_catalog_tables")

CATALOG_TABLES = {
    "datasets",
    "dataset_fields",
    "dataset_connections",
    "dataset_links",
    "project_catalog_projections",
}

UNIVERSAL_DATASET_COLUMNS = {"kind", "physical_key", "location", "locator"}
DB_TABLE_SPECIFIC_COLUMNS = {"dialect", "host", "port", "database", "schema", "table"}
ATTRIBUTION_COLUMNS = {
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
    return engine


def _run(engine, operation):
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            operation()


def _tables(engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names()) & CATALOG_TABLES


def _columns(engine, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(engine).get_columns(table)}


def test_upgrade_is_idempotent_and_downgrade_restores_previous_state():
    engine = _database()

    _run(engine, migration.upgrade)
    assert _tables(engine) == CATALOG_TABLES
    inspector = sa.inspect(engine)
    unique_names = {item["name"] for item in inspector.get_unique_constraints("datasets")}
    assert "uq_datasets_organization_physical_key" in unique_names
    index_names = {item["name"] for item in inspector.get_indexes("dataset_links")}
    assert {"ix_dataset_links_dataset_id", "ix_dataset_links_project_id"} <= index_names
    assert "ix_datasets_kind" in {item["name"] for item in inspector.get_indexes("datasets")}

    _run(engine, migration.upgrade)
    assert _tables(engine) == CATALOG_TABLES

    _run(engine, migration.downgrade)
    assert _tables(engine) == set()

    _run(engine, migration.upgrade)
    assert _tables(engine) == CATALOG_TABLES


def test_datasets_are_universal_and_carry_attribution_columns():
    engine = _database()
    _run(engine, migration.upgrade)

    dataset_columns = _columns(engine, "datasets")
    assert UNIVERSAL_DATASET_COLUMNS <= dataset_columns
    assert not (DB_TABLE_SPECIFIC_COLUMNS & dataset_columns)
    for table, expected in ATTRIBUTION_COLUMNS.items():
        assert expected <= _columns(engine, table)
