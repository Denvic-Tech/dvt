from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

from services.task_worker import celery_app as runtime

from src.enums import ExtensionDepsStatus
from src.modules.extension_management.domain.value_objects import ExtensionManifest
from src.modules.extension_management.infra import management_service
from src.modules.extension_management.infra.db_models import ExtensionRecord


@pytest.fixture
async def extension_runtime(async_test_db_engine, monkeypatch, tmp_path):
    factory = async_sessionmaker(async_test_db_engine, expire_on_commit=False)
    manifest = ExtensionManifest(
        name="test-extension", version="1.0", requirements=["example-package==1.0"],
    )
    async with factory() as session:
        record = ExtensionRecord(
            name=manifest.name, display_name=manifest.name, is_installed=True,
            is_enabled=True, deps_status=ExtensionDepsStatus.READY, current_version="1.0",
            install_path=str(tmp_path), installed_at=datetime(2026, 1, 1, tzinfo=UTC),
            manifest_json=manifest.model_dump(mode="json"),
        )
        session.add(record)
        await session.commit()

    reloads = AsyncMock()
    deps = AsyncMock()
    monkeypatch.setattr(runtime, "AsyncSessionLocal", factory)
    monkeypatch.setattr(runtime, "ensure_extension_deps_installed", deps)
    monkeypatch.setattr(runtime, "_extension_runtime_initialized", False)
    monkeypatch.setattr(runtime, "_extension_runtime_generation", None)
    monkeypatch.setattr(management_service, "iter_extension_roots", lambda: [tmp_path])
    monkeypatch.setattr(management_service, "load_manifest_payload", lambda _root: manifest)
    monkeypatch.setattr(management_service, "process_pending_deletions", lambda _remove: None)

    async def manager(*, session):
        impl = management_service.ExtensionManager(session, SimpleNamespace())
        monkeypatch.setattr(impl, "_refresh_runtime", reloads)
        return SimpleNamespace(sync_installed_extensions=impl.sync_installed_extensions,
                               close=AsyncMock())

    monkeypatch.setattr(runtime, "get_extension_manager", manager)
    return factory, deps, reloads


@pytest.mark.asyncio
async def test_two_workers_settle_after_sync_and_catalog_updates(extension_runtime):
    factory, deps, reloads = extension_runtime
    generations = {}
    for _ in range(3):
        for worker in ("worker-a", "worker-b"):
            runtime._extension_runtime_initialized = worker in generations
            runtime._extension_runtime_generation = generations.get(worker)
            await runtime._ensure_extension_runtime_for_task_process_async(
                required_extension_names={"test-extension"},
            )
            generations[worker] = runtime._extension_runtime_generation

    assert reloads.await_count == 2
    assert deps.await_count == 2
    assert generations["worker-a"] == generations["worker-b"]

    async with factory() as session:
        record = (await session.execute(select(ExtensionRecord))).scalars().one()
        record.description = "New catalog text"
        record.last_version = "2.0"
        record.available_versions = ["2.0", "1.0"]
        record.updated_at = datetime.now(UTC)
        session.add(record)
        await session.commit()

    assert await runtime._ensure_extension_runtime_for_task_process_async(
        required_extension_names={"test-extension"},
    ) is False
    assert reloads.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["version", "reinstall", "disabled", "removed", "manifest"])
async def test_runtime_generation_detects_real_changes(extension_runtime, change):
    factory, _, _ = extension_runtime
    before = await runtime._read_extension_runtime_generation()
    async with factory() as session:
        record = (await session.execute(select(ExtensionRecord))).scalars().one()
        if change == "version":
            record.current_version = "2.0"
        elif change == "reinstall":
            record.installed_at += timedelta(seconds=1)
        elif change == "disabled":
            record.is_enabled = False
        elif change == "removed":
            record.is_installed = False
            record.install_path = None
        else:
            record.manifest_json = {**record.manifest_json, "requirements": ["example-package==2.0"]}
        session.add(record)
        await session.commit()
    assert await runtime._read_extension_runtime_generation() != before


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["not_ready", "disabled", "error", "removed"])
async def test_unchanged_process_still_checks_required_extension_readiness(extension_runtime, change):
    factory, deps, reloads = extension_runtime
    await runtime._ensure_extension_runtime_for_task_process_async(
        required_extension_names={"test-extension"},
    )
    async with factory() as session:
        record = (await session.execute(select(ExtensionRecord))).scalars().one()
        if change == "not_ready":
            record.deps_status = ExtensionDepsStatus.INSTALLING
        elif change == "disabled":
            record.is_enabled = False
        elif change == "error":
            record.error_message = "Broken extension"
        else:
            record.is_installed = False
        session.add(record)
        await session.commit()

    with pytest.raises(RuntimeError, match="Required extension"):
        await runtime._ensure_extension_runtime_for_task_process_async(
            required_extension_names={"test-extension"},
        )
    assert deps.await_count == 1
    assert reloads.await_count == 1


@pytest.mark.asyncio
async def test_dependency_failure_does_not_acknowledge_or_load_generation(extension_runtime):
    _, deps, reloads = extension_runtime
    deps.side_effect = RuntimeError("Local dependency installation failed")
    with pytest.raises(RuntimeError, match="Local dependency"):
        await runtime._ensure_extension_runtime_for_task_process_async(
            required_extension_names={"test-extension"},
        )
    assert runtime._extension_runtime_initialized is False
    assert runtime._extension_runtime_generation is None
    reloads.assert_not_awaited()


@pytest.mark.asyncio
async def test_reinstall_same_version_reloads_once_per_worker(extension_runtime):
    factory, deps, reloads = extension_runtime
    generations = {}
    for worker in ("a", "b"):
        runtime._extension_runtime_initialized = False
        await runtime._ensure_extension_runtime_for_task_process_async()
        generations[worker] = runtime._extension_runtime_generation

    async with factory() as session:
        record = (await session.execute(select(ExtensionRecord))).scalars().one()
        record.installed_at += timedelta(seconds=1)
        session.add(record)
        await session.commit()

    for _ in range(2):
        for worker in ("a", "b"):
            runtime._extension_runtime_generation = generations[worker]
            await runtime._ensure_extension_runtime_for_task_process_async()
            generations[worker] = runtime._extension_runtime_generation

    assert deps.await_count == 4
    assert reloads.await_count == 4


@pytest.mark.asyncio
async def test_repeated_full_sync_does_not_write_extension_state(extension_runtime):
    factory, _, _ = extension_runtime
    async with factory() as session:
        manager = await runtime.get_extension_manager(session=session)
        await manager.sync_installed_extensions()
        record = (await session.execute(select(ExtensionRecord))).scalars().one()
        timestamp = record.updated_at
        for _ in range(3):
            await manager.sync_installed_extensions()
            await session.refresh(record)
            assert record.updated_at == timestamp
