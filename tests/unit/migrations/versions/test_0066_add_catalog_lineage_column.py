import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

base = importlib.import_module("migrations.versions.0064_add_data_catalog_tables")
migration = importlib.import_module("migrations.versions.0066_add_catalog_lineage_column")


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


def _columns(engine) -> set[str]:
    return {column["name"] for column in sa.inspect(engine).get_columns("project_catalog_projections")}


def test_lineage_column_is_added_idempotently_and_removed_on_downgrade():
    engine = _database()
    _run(engine, base.upgrade)
    assert "lineage" not in _columns(engine)

    _run(engine, migration.upgrade)
    assert "lineage" in _columns(engine)
    _run(engine, migration.upgrade)
    assert "lineage" in _columns(engine)

    _run(engine, migration.downgrade)
    assert "lineage" not in _columns(engine)
    _run(engine, migration.downgrade)
