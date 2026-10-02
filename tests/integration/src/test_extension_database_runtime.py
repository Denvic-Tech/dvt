from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

from src.modules.extension_management.infra.database import (
    extension_async_session,
    extension_schema_name,
)
from src.modules.extension_management.infra.migrations import ExtensionMigrationManager
from src.modules.extension_management.infra.runtime.loader import load_manifest


def _write_extension(
    root: Path,
    *,
    table_name: str,
    revision: str = "0001",
    broken: bool = False,
    with_public_fk: bool = False,
) -> None:
    versions = root / "backend" / "migrations" / "versions"
    versions.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f"""
[project]
name = "{root.name}"
version = "1.0.0"

[tool.dvt_extension]
name = "{root.name}"

[tool.dvt_extension.backend]
migrations_dir = "backend/migrations"
""",
        encoding="utf-8",
    )

    if broken:
        upgrade_body = "    op.execute('THIS IS INVALID SQL')"
    else:
        fk_column = (
            ", sa.Column('parent_id', sa.Integer(), sa.ForeignKey('public.core_parent.id'))"
            if with_public_fk
            else ""
        )
        upgrade_body = (
            f"    op.create_table('{table_name}', sa.Column('id', sa.Integer(), primary_key=True){fk_column})"
        )

    (versions / f"{revision}_initial.py").write_text(
        f"""
from alembic import op
import sqlalchemy as sa

revision = {revision!r}
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
{upgrade_body}

def downgrade():
    pass
""",
        encoding="utf-8",
    )


def _load(root: Path, engine):
    from src.modules.extension_management.domain.policies import canonical_extension_name
    from src.modules.extension_management.infra.db_models import ExtensionRecord

    ExtensionRecord.__table__.create(engine, checkfirst=True)
    with Session(engine) as session:
        session.add(ExtensionRecord(
            name=canonical_extension_name(root.name), display_name=root.name,
            storage_schema=extension_schema_name(root.name),
            manifest_json={"legacy_names": [root.name]},
        ))
        session.commit()
    extension = load_manifest(root)
    assert extension is not None
    return extension


@pytest.mark.asyncio
async def test_extension_migrations_are_isolated_and_sessions_do_not_leak_search_path(
    postgres_container, tmp_path: Path
) -> None:
    sync_url = postgres_container.get_connection_url()
    sync_engine = sa.create_engine(sync_url)
    async_engine = create_async_engine(sync_url)
    manager = ExtensionMigrationManager(sync_engine)

    extension_a_root = tmp_path / "extension_a"
    extension_b_root = tmp_path / "extension_b"
    _write_extension(extension_a_root, table_name="foo")
    _write_extension(extension_b_root, table_name="bar")

    manager.upgrade(_load(extension_a_root, sync_engine))
    manager.upgrade(_load(extension_b_root, sync_engine))

    schema_a = extension_schema_name("extension_a")
    schema_b = extension_schema_name("extension_b")
    with Session(sync_engine) as session:
        assert session.execute(sa.text(f"SELECT to_regclass('{schema_a}.foo')")).scalar()
        assert session.execute(sa.text(f"SELECT to_regclass('{schema_b}.bar')")).scalar()
        assert session.execute(sa.text("SELECT to_regclass('public.foo')")).scalar() is None
        assert session.execute(sa.text("SELECT to_regclass('public.bar')")).scalar() is None
        assert session.execute(
            sa.text(f"SELECT to_regclass('{schema_a}.alembic_version')")
        ).scalar()
        assert session.execute(
            sa.text(f"SELECT to_regclass('{schema_b}.alembic_version')")
        ).scalar()

    async with extension_async_session("extension_a", _engine=async_engine) as session:
        await session.execute(sa.text("CREATE TABLE local_items (id integer primary key)"))
        await session.commit()
        await session.execute(sa.text("INSERT INTO local_items VALUES (1)"))
        await session.commit()
        assert (await session.execute(sa.text("SELECT count(*) FROM local_items"))).scalar() == 1
        await session.rollback()
        assert schema_a in (await session.execute(sa.text("SHOW search_path"))).scalar()

    async with extension_async_session("extension_b", _engine=async_engine) as session_b:
        assert schema_b in (await session_b.execute(sa.text("SHOW search_path"))).scalar()
        assert schema_a not in (await session_b.execute(sa.text("SHOW search_path"))).scalar()

    async with async_engine.connect() as connection:
        search_path = (await connection.execute(sa.text("SHOW search_path"))).scalar()
        assert schema_a not in search_path
        assert schema_b not in search_path

    await async_engine.dispose()
    sync_engine.dispose()


def test_extension_migration_failure_isolated_fk_to_public_and_drop(
    postgres_container, tmp_path: Path
) -> None:
    engine = sa.create_engine(postgres_container.get_connection_url())
    manager = ExtensionMigrationManager(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.text("CREATE TABLE public.core_parent (id integer primary key)")
        )

    good_root = tmp_path / "extension_good"
    broken_root = tmp_path / "extension_broken"
    _write_extension(good_root, table_name="child", with_public_fk=True)
    _write_extension(broken_root, table_name="broken_table", broken=True)

    with pytest.raises(sa.exc.ProgrammingError):
        manager.upgrade(_load(broken_root, engine))

    manager.upgrade(_load(good_root, engine))
    good_schema = extension_schema_name("extension_good")
    broken_schema = extension_schema_name("extension_broken")
    with engine.connect() as connection:
        assert connection.execute(
            sa.text(f"SELECT to_regclass('{good_schema}.child')")
        ).scalar()
        assert connection.execute(
            sa.text("SELECT to_regclass('public.core_parent')")
        ).scalar()
        assert connection.execute(
            sa.text("SELECT to_regclass('public.child')")
        ).scalar() is None

    manager.drop_schema("extension_good")
    with engine.connect() as connection:
        assert connection.execute(
            sa.text(f"SELECT to_regnamespace('{good_schema}')")
        ).scalar() is None
        # A failed migration may still leave its schema, but it must not affect others.
        assert connection.execute(
            sa.text(f"SELECT to_regnamespace('{broken_schema}')")
        ).scalar() is not None

    engine.dispose()


def test_extension_data_and_history_survive_reinstall_without_drop(
    postgres_container, tmp_path: Path
) -> None:
    engine = sa.create_engine(postgres_container.get_connection_url())
    manager = ExtensionMigrationManager(engine)
    extension_root = tmp_path / "persistent-extension"
    _write_extension(extension_root, table_name="settings")
    extension = _load(extension_root, engine)
    manager.upgrade(extension)
    schema_name = extension_schema_name(extension.name)

    with engine.begin() as connection:
        connection.execute(
            sa.text(f'INSERT INTO "{schema_name}".settings (id) VALUES (7)')
        )

    # Default uninstall deliberately performs no downgrade/drop. Reinstalling
    # the same files therefore sees the existing per-extension Alembic history.
    manager.upgrade(extension)

    with engine.connect() as connection:
        assert connection.execute(
            sa.text(f'SELECT id FROM "{schema_name}".settings')
        ).scalar_one() == 7
        assert connection.execute(
            sa.text(f'SELECT version_num FROM "{schema_name}".alembic_version')
        ).scalar_one() == "0001"

    engine.dispose()


@pytest.mark.asyncio
async def test_identity_migration_keeps_postgres_data_and_alias_state(
    postgres_container, monkeypatch,
):
    import importlib
    import uuid

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.modules.extension_management.infra import database, state_manager
    from src.modules.extension_management.infra.db_models import ExtensionRecord

    database_name = "identity_" + uuid.uuid4().hex
    admin = sa.create_engine(postgres_container.get_connection_url(), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.exec_driver_sql(f"CREATE DATABASE {database_name}")
    engine = sa.create_engine(admin.url.set(database=database_name))
    async_engine = create_async_engine(admin.url.set(database=database_name))
    old_name = "Bitrix24 Connector"
    canonical = "bitrix24-connector"
    old_schema = extension_schema_name(old_name)
    migration = importlib.import_module("migrations.versions.0062_canonical_extension_identity")
    try:
        ExtensionRecord.__table__.create(engine)
        with Session(engine) as session:
            session.add(ExtensionRecord(
                id="retained-id", name=old_name, display_name="Bitrix 24 Connector",
                is_installed=True, install_path="/extensions/bitrix24-connector",
                manifest_json={"name": old_name, "package_name": canonical},
                state_json={"license": {"value": "retained"}, "counter": {"value": 0}},
            ))
            session.commit()
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE extensions DROP COLUMN storage_schema")
            connection.exec_driver_sql(f'CREATE SCHEMA "{old_schema}"')
            connection.exec_driver_sql(f'CREATE TABLE "{old_schema}".settings (value integer)')
            connection.exec_driver_sql(f'INSERT INTO "{old_schema}".settings VALUES (17)')
        with (
            engine.begin() as connection,
            Operations.context(MigrationContext.configure(connection)),
        ):
            migration.upgrade()
        monkeypatch.setattr(database, "default_engine", engine)
        monkeypatch.setattr(state_manager, "engine", engine)
        monkeypatch.setattr(state_manager, "get_async_session_acm", lambda: AsyncSession(async_engine))

        assert database.resolve_storage_schema(canonical) == old_schema
        assert database.resolve_storage_schema(old_name) == old_schema
        for name in (canonical, old_name):
            async with extension_async_session(name, _engine=async_engine) as session:
                assert (await session.execute(sa.text("SELECT value FROM settings"))).scalar() == 17
                await session.commit()
                assert (await session.execute(sa.text("SELECT value FROM settings"))).scalar() == 17
            await state_manager.ExtensionStateManager.async_update_state(
                name, lambda state: {"value": state["value"] + 1}, key="counter",
            )
        assert state_manager.ExtensionStateManager.get_state(old_name, "counter") == {"value": 2}
        assert await state_manager.ExtensionStateManager.async_get_state(canonical, "license") == {
            "value": "retained",
        }
        with Session(engine) as session:
            record = session.get(ExtensionRecord, "retained-id")
            assert record.name == canonical
            assert record.install_path == "/extensions/bitrix24-connector"
        manager = ExtensionMigrationManager(engine)
        assert manager.ensure_schema(canonical) == old_schema
        with engine.connect() as connection:
            assert connection.execute(sa.text("SELECT to_regnamespace(:name)"), {
                "name": extension_schema_name(canonical),
            }).scalar() is None
        manager.drop_schema(old_name)
        with engine.connect() as connection:
            assert connection.execute(sa.text("SELECT to_regnamespace(:name)"), {
                "name": old_schema,
            }).scalar() is None
    finally:
        await async_engine.dispose()
        engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f"DROP DATABASE {database_name} WITH (FORCE)")
        admin.dispose()
