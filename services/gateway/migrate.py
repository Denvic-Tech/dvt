import asyncio
import sys
from pathlib import Path

from sqlmodel import Session, create_engine

from src.db import AsyncSessionLocal
from src.extensions.deletion_queue import process_pending_deletions
from src.extensions.errors import stage_error
from src.extensions.loader import iter_extension_roots, load_manifest
from src.extensions.migrations import ExtensionMigrationManager
from src.logger import logger
from src.managers.extension_db_manager import ExtensionDBManager
from src.managers.extension_install_manager import ExtensionsInstallManager
from src.utils import waiting
from src.utils.extensions import ensure_extension_deps_installed
from src.utils.migrations import run_alembic_upgrade_head

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


def run_migrations():
    logger.info("Starting database migrations...")

    engine = create_engine(
        url=config.POSTGRES.DATABASE_URL,
        echo=True
    )

    with Session(engine) as session:
        waiting.wait_for_db(session=session)

    run_alembic_upgrade_head(
        alembic_ini=config.PROJECT.ALEMBIC_INI,
        engine=engine
    )

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_prepare_extension_migrations(engine))


if __name__ == '__main__':
    run_migrations()
