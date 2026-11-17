import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

migration = importlib.import_module("migrations.versions.0067_add_node_column_annotations")


def _database():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    sa.Table(
        "graph_nodes",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("ui_id", sa.String, nullable=False),
        sa.Column("project_id", sa.String, nullable=False),
        sa.UniqueConstraint("ui_id", "project_id"),
    )
    metadata.create_all(engine)
    return engine


def _run(engine, operation):
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            operation()


def test_annotations_table_is_created_idempotently_and_dropped_on_downgrade():
    engine = _database()

    _run(engine, migration.upgrade)
    inspector = sa.inspect(engine)
    assert inspector.has_table("node_column_annotations")
    columns = {column["name"] for column in inspector.get_columns("node_column_annotations")}
    assert {"project_id", "node_id", "port", "column_name", "description", "origin_key"} <= columns
    assert any(
        index["name"] == "ix_node_column_annotations_project_id"
        for index in inspector.get_indexes("node_column_annotations")
    )
    foreign_keys = inspector.get_foreign_keys("node_column_annotations")
    assert foreign_keys[0]["referred_table"] == "graph_nodes"
    assert foreign_keys[0]["options"].get("ondelete") == "CASCADE"

    _run(engine, migration.upgrade)
    assert sa.inspect(engine).has_table("node_column_annotations")

    _run(engine, migration.downgrade)
    assert not sa.inspect(engine).has_table("node_column_annotations")
    _run(engine, migration.downgrade)
