import asyncio
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext as AlembicContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlmodel import Session, create_engine

from src.db import AsyncSessionLocal
from src.logger import logger
from src.modules.extension_management.infra.dependency_bootstrap import (
    ensure_extension_deps_installed,
)
from src.modules.extension_management.infra.errors import stage_error
from src.modules.extension_management.infra.migrations import ExtensionMigrationManager
from src.modules.extension_management.infra.packages.deletion_queue import (
    process_pending_deletions,
)
from src.modules.extension_management.infra.packages.installer import (
    ExtensionsInstallManager,
)
from src.modules.extension_management.infra.repositories.db import ExtensionDBManager
from src.modules.extension_management.infra.runtime.loader import (
    iter_extension_roots,
    load_manifest,
)
from src.utils import waiting
from src.utils.deployment_migrations import CREATE_RECEIPTS, RECEIPTS, MigrationContext

import config


async def _sync_installed_extension_records() -> list:
    install_manager = ExtensionsInstallManager()
    process_pending_deletions(install_manager._remove_install_root)

    discovered: dict[str, dict] = {}
    failures: dict[str, Exception] = {}
    for root_dir in iter_extension_roots():
        try:
            manifest = load_manifest(root_dir, extension_name=root_dir.name)
            if manifest is None:
                raise ValueError(f"Manifest not found in '{root_dir}'")
            discovered[root_dir.name] = {"root_dir": root_dir, "manifest": manifest}
        except Exception as exc:
            failures[root_dir.name] = exc
            logger.exception("Extension manifest preparation failed for '{}'", root_dir.name)

    async with AsyncSessionLocal() as session:
        db_manager = ExtensionDBManager(session)
        records = await db_manager.sync_installed_extensions(discovered)
        by_name = {record.name: record for record in records}
        for name, exc in failures.items():
            record = by_name.get(name)
            if record is not None:
                await db_manager.set_runtime_error(
                    record, stage_error("Manifest validation failed", exc)
                )
        return await db_manager.list_extensions()


async def _record_extension_migration_result(
    extension_name: str, error_message: str | None
) -> None:
    async with AsyncSessionLocal() as session:
        db_manager = ExtensionDBManager(session)
        extension = await db_manager.get_extension(extension_name)
        if extension is None:
            return
        if error_message is not None:
            await db_manager.set_runtime_error(extension, error_message)
        elif (
            extension.error_message
            and extension.error_message.startswith("Extension migration failed:")
        ):
            await db_manager.set_runtime_error(extension, None)


async def _prepare_extension_migrations(engine) -> None:
    await _sync_installed_extension_records()
    await ensure_extension_deps_installed()
    async with AsyncSessionLocal() as session:
        records = await ExtensionDBManager(session).list_extensions()
    migration_manager = ExtensionMigrationManager(engine)

    for extension in records:
        if not extension.is_installed or not extension.install_path:
            continue
        if (
            extension.error_message
            and extension.error_message.startswith(
                ("Manifest validation failed:", "Dependency installation failed:")
            )
        ):
            continue
        try:
            manifest = load_manifest(
                Path(extension.install_path), extension_name=extension.name
            )
            if manifest is None:
                raise ValueError(f"Manifest not found in '{extension.install_path}'")
            await asyncio.to_thread(migration_manager.upgrade, manifest)
            await _record_extension_migration_result(extension.name, None)
        except Exception as exc:
            message = stage_error("Extension migration failed", exc)
            logger.exception("Extension migration failed for '{}'", extension.name)
            await _record_extension_migration_result(extension.name, message)


MIGRATION_LOCK = 0x4456545F4D494752


def _migrate(engine, alembic: Config, target: str, deployment: MigrationContext | None) -> None:
    # A session-level lock survives the core commit and covers extension DB/file preparation.
    with engine.connect() as connection:
        if not connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": MIGRATION_LOCK}
        ).scalar_one():
            raise RuntimeError("Another process holds the database migration lock")
        connection.commit()

        with connection.begin():
            revisions = AlembicContext.configure(connection).get_current_heads()
            phase = deployment.phase(connection) if deployment else None
            if phase in {"done", "resumed"}:
                if revisions != (target,):
                    raise RuntimeError("The recorded migration no longer matches the database")
                if phase == "done":
                    deployment.assert_frozen(connection)
                deployment.assert_extensions(connection)
                return

            if deployment:
                deployment.assert_frozen(connection)
                expected = (target,) if phase == "core" else (
                    (deployment.source,) if deployment.source is not None else ()
                )
                if revisions != expected:
                    raise RuntimeError("The live source revision does not match the selected transition")
                if deployment.source is None and phase is None and connection.execute(
                    text("""
                        SELECT EXISTS (
                            SELECT 1 FROM pg_tables
                            WHERE schemaname = ANY(current_schemas(false))
                              AND tablename <> 'alembic_version'
                        )
                    """)
                ).scalar_one():
                    raise RuntimeError("Initial installation requires an empty database")
            if phase != "core":
                alembic.attributes["connection"] = connection
                if revisions != (target,):
                    command.upgrade(alembic, target)
                if AlembicContext.configure(connection).get_current_heads() != (target,):
                    raise RuntimeError("The migration did not reach the packaged revision")
                if deployment:
                    connection.execute(text("CREATE SCHEMA IF NOT EXISTS dvt_release_control"))
                    connection.execute(text(CREATE_RECEIPTS))
                    connection.execute(
                        text(f"""
                            INSERT INTO {RECEIPTS} (operation_id, context, phase)
                            VALUES (:operation, CAST(:context AS jsonb), 'core')
                        """),
                        {"operation": deployment.operation_id, "context": deployment.encoded},
                    )

        asyncio.run(_prepare_extension_migrations(engine))
        if deployment:
            with connection.begin():
                deployment.assert_database(connection)
                if AlembicContext.configure(connection).get_current_heads() != (target,):
                    raise RuntimeError("The target revision changed during extension preparation")
                deployment.assert_extensions(connection)
                connection.execute(
                    text(f"UPDATE {RECEIPTS} SET phase = 'done' WHERE operation_id = :operation"),
                    {"operation": deployment.operation_id},
                )


def run_migrations() -> None:
    logger.info("Starting database migrations")
    deployment = MigrationContext.read()
    target = waiting._read_expected_alembic_revision(config.PROJECT.RELEASE_FILE)
    alembic = Config(str(config.PROJECT.ALEMBIC_INI))
    scripts = ScriptDirectory.from_config(alembic)
    if scripts.get_heads() != [target] or (deployment and deployment.target != target):
        raise RuntimeError("The selected schema revision does not match this Gateway image")
    if deployment and deployment.source and deployment.source != target:
        # A source database on a newer, unrelated, or unknown branch must never be stamped.
        tuple(scripts.iterate_revisions(target, deployment.source))
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # Closing the physical connection always releases its advisory lock, even on failure.
    engine = create_engine(url=config.POSTGRES.DATABASE_URL, poolclass=NullPool)
    try:
        with Session(engine) as session:
            waiting.wait_for_db(session=session)
        _migrate(engine, alembic, target, deployment)
    finally:
        engine.dispose()


if __name__ == '__main__':
    run_migrations()
