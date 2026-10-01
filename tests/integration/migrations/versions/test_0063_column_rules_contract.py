import importlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects.postgresql import JSONB

from src.schemas.internal.node_data import NodeData

migration = importlib.import_module("migrations.versions.0063_column_rules_contract")


@pytest.mark.docker_required
def test_postgresql_transaction_retry_roundtrip_and_runtime_payload(postgres_container):
    engine = sa.create_engine(postgres_container.get_connection_url())
    metadata = sa.MetaData()
    nodes = sa.Table(
        "graph_nodes",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String),
        sa.Column("ui_id", sa.String),
        sa.Column("project_id", sa.String),
        sa.Column("input_values", JSONB),
    )
    edges = sa.Table(
        "graph_edges",
        metadata,
        sa.Column("target", sa.String),
        sa.Column("project_id", sa.String),
        sa.Column("target_handle", sa.String),
    )
    metadata.create_all(engine)
    rows = [
        {
            "id": f"{index:04d}",
            "name": name,
            "ui_id": f"ui-{index}",
            "project_id": "p",
            "input_values": {
                "column": migration.const("date"),
                "column_name": migration.const("new"),
            },
        }
        for index, name in enumerate(list(migration.NODES) * 65)
    ]
    with engine.begin() as connection:
        connection.execute(nodes.insert(), rows)
        connection.execute(
            edges.insert(),
            [
                {
                    "project_id": "p",
                    "target": "ui-2",
                    "target_handle": "input-timezone",
                }
            ],
        )
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            transaction.rollback()  # Simulate an interrupted deployment.
        with engine.begin() as connection:
            assert (
                connection.execute(sa.select(nodes.c.input_values).limit(1)).scalar_one()
                == rows[0]["input_values"]
            )
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                first = dict(connection.execute(sa.select(nodes.c.id, nodes.c.input_values)).all())
                migration.upgrade()
                assert (
                    dict(connection.execute(sa.select(nodes.c.id, nodes.c.input_values)).all())
                    == first
                )
                # Persisted payloads remain valid for application graph deserialization.
                for row in rows:
                    NodeData(name=row["name"], inputs=first[row["id"]])
                migration.downgrade()
                assert dict(
                    connection.execute(sa.select(nodes.c.id, nodes.c.input_values)).all()
                ) == {row["id"]: row["input_values"] for row in rows}
                migration.upgrade()
                assert (
                    dict(connection.execute(sa.select(nodes.c.id, nodes.c.input_values)).all())
                    == first
                )
    finally:
        metadata.drop_all(engine)
        engine.dispose()
