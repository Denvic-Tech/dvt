import importlib
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url

from src.schemas.internal.node_data import NodeData

migration = importlib.import_module("migrations.versions.0063_column_rules_contract")


@pytest.mark.docker_required
def test_postgresql_transaction_retry_roundtrip_and_runtime_payload(postgres_container):
    base_url = make_url(postgres_container.get_connection_url())
    admin_db_name = base_url.database
    assert admin_db_name
    test_db_name = f"migration_0063_{uuid4().hex[:8]}"
    admin_url = base_url.set(database=admin_db_name)
    admin_engine = sa.create_engine(
        admin_url.render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    with admin_engine.connect() as connection:
        connection.execute(sa.text(f'CREATE DATABASE "{test_db_name}"'))

    engine = sa.create_engine(
        base_url.set(database=test_db_name).render_as_string(hide_password=False)
    )
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
        with admin_engine.connect() as connection:
            connection.execute(
                sa.text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :db_name
                      AND pid <> pg_backend_pid()
                    """
                ),
                {"db_name": test_db_name},
            )
            connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{test_db_name}"'))
        admin_engine.dispose()
