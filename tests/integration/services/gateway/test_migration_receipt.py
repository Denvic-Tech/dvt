"""Exercise the real Alembic history and durable receipts on a disposable PostgreSQL."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext as AlembicContext
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

from services.gateway import migrate
from services.installation_manager.infrastructure.application_host import ComposeApplicationHost
from services.installation_manager.infrastructure.maintenance_database import frozen_sql

from src.utils.deployment_migrations import DATABASE_ID_SQL, MigrationContext

import config

pytestmark = pytest.mark.docker_required


@pytest.fixture
def postgres():
    with PostgresContainer("postgres:15.3-alpine", driver="psycopg") as container:
        engine = create_engine(container.get_connection_url(), poolclass=NullPool)
        try:
            yield engine
        finally:
            engine.dispose()


def deployment(engine, monkeypatch, *, source=None, required=(), operation=None):
    with engine.connect() as connection:
        database = connection.execute(text(DATABASE_ID_SQL)).scalar_one()
    monkeypatch.setenv(
        "DVT_MIGRATION_CONTEXT",
        json.dumps(
            {
                "operation": str(operation or uuid4()),
                "instance": str(uuid4()),
                "source": source,
                "target": "0070",
                "image": "sha256:" + "1" * 64,
                "manifest": "sha256:" + "2" * 64,
                "database": database,
                "required_extensions": list(required),
            }
        ),
    )
    return MigrationContext.read()


def apply(engine, context):
    migrate._migrate(engine, Config(str(config.PROJECT.ALEMBIC_INI)), "0070", context)


def phase(engine, context):
    with engine.connect() as connection:
        return context.phase(connection)


def test_lock_and_transactional_receipt_on_fresh_database(postgres, monkeypatch):
    context = deployment(postgres, monkeypatch)
    prepare_calls = []

    async def prepare(_engine):
        prepare_calls.append(True)

    monkeypatch.setattr(migrate, "_prepare_extension_migrations", prepare)
    with postgres.connect() as competitor:
        competitor.execute(text("SELECT pg_advisory_lock(:key)"), {"key": migrate.MIGRATION_LOCK})
        with pytest.raises(RuntimeError, match="holds the database migration lock"):
            apply(postgres, context)
    assert phase(postgres, context) is None

    upgrade = migrate.command.upgrade

    def broken_upgrade(*args):
        upgrade(*args)
        raise RuntimeError("injected fault before core receipt")

    with monkeypatch.context() as fault:
        fault.setattr(migrate.command, "upgrade", broken_upgrade)
        with pytest.raises(RuntimeError, match="injected fault"):
            apply(postgres, context)
    with postgres.connect() as connection:
        assert AlembicContext.configure(connection).get_current_heads() == ()
        assert context.phase(connection) is None

    apply(postgres, context)
    assert phase(postgres, context) == "done"
    apply(postgres, context)
    assert len(prepare_calls) == 1

    outside = deployment(postgres, monkeypatch, operation=context.operation_id)
    with pytest.raises(RuntimeError, match="receipt belongs to another deployment"):
        apply(postgres, outside)

    # A new logical database in the same cluster cannot reuse the receipt.
    with postgres.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text("CREATE DATABASE replacement TEMPLATE template0"))
    replacement = create_engine(postgres.url.set(database="replacement"), poolclass=NullPool)
    try:
        with pytest.raises(RuntimeError, match="different PostgreSQL database"):
            apply(replacement, context)
    finally:
        replacement.dispose()


def test_required_extension_and_same_id_resume_are_independent_checkpoints(postgres, monkeypatch):
    async def no_extensions(_engine):
        return None

    monkeypatch.setattr(migrate, "_prepare_extension_migrations", no_extensions)
    apply(postgres, None)
    operation = uuid4()
    update = deployment(
        postgres, monkeypatch, source="0070", required=("required-ext",), operation=operation
    )
    with pytest.raises(RuntimeError, match="does not own the frozen"):
        apply(postgres, update)
    with postgres.begin() as connection:
        connection.execute(
            text("UPDATE task_admission_control SET operation_id = :op, frozen = true"),
            {"op": operation},
        )

    with pytest.raises(RuntimeError, match="Required extensions are unavailable"):
        apply(postgres, update)
    assert phase(postgres, update) == "core"
    with postgres.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO extensions (
                id, name, display_name, description, is_enabled, is_installed, deps_status,
                manifest_json, state_json, created_at, updated_at
            )
            VALUES ('fixture', 'required-ext', 'Required', '', true, true, 'READY',
                    '{}', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """)
        )
    apply(postgres, update)
    assert phase(postgres, update) == "done"

    # Exercise the production resume SQL via a real PostgreSQL connection.
    class DatabaseOnly(ComposeApplicationHost):
        def __init__(self):
            pass

        @staticmethod
        def sql(_pg, query):
            with postgres.begin() as connection:
                result = connection.exec_driver_sql(query)
                return (result.scalar() or "") if result.returns_rows else ""

    host = DatabaseOnly()
    with postgres.begin() as connection:
        connection.execute(
            text("UPDATE task_admission_control SET operation_id = :op"), {"op": uuid4()}
        )
    assert not host.resume("fixture", update.encoded)
    with pytest.raises(RuntimeError, match="does not own the frozen"):
        apply(postgres, update)

    with postgres.begin() as connection:
        connection.execute(
            text("UPDATE task_admission_control SET operation_id = :op"), {"op": operation}
        )
        assert connection.exec_driver_sql(frozen_sql(operation)).scalar() == "frozen"
    assert host.resume("fixture", update.encoded)
    assert host.resume("fixture", update.encoded)
    assert phase(postgres, update) == "resumed"
    apply(postgres, update)
