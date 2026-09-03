from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import Session, select

from services.task_worker import celery_app as worker_runtime
from src.enums import ExtensionDepsStatus
from src.models.extension import ExtensionRecord

pytestmark = pytest.mark.docker_required


@pytest.mark.asyncio(loop_scope="session")
async def test_persistent_worker_reloads_registry_after_extension_install_and_update(
    test_db_engine,
    test_db_async_engine,
    monkeypatch,
):
    name = f"runtime-generation-{uuid4().hex}"
    installed_at = datetime.now(tz=UTC)
    record = ExtensionRecord(
        name=name,
        display_name=name,
        is_installed=True,
        is_enabled=True,
        deps_status=ExtensionDepsStatus.READY,
        current_version="1.0.0",
        install_path=f"/tmp/{name}",
        installed_at=installed_at,
    )
    with Session(test_db_engine) as session:
        session.add(record)
        session.commit()

    factory = async_sessionmaker(test_db_async_engine, expire_on_commit=False)
    visible_nodes: dict[str, str] = {}
    reload_count = 0

    class _Manager:
        distributor_client = None

        async def sync_installed_extensions(self):
            nonlocal reload_count
            reload_count += 1
            async with factory() as session:
                current = (
                    await session.execute(
                        select(ExtensionRecord).where(ExtensionRecord.name == name)
                    )
                ).scalars().one()
            visible_nodes[name] = str(current.current_version)

    async def _manager(*, session):
        assert session is not None
        return _Manager()

    async def _deps(**_kwargs):
        return None

    monkeypatch.setattr(worker_runtime, "AsyncSessionLocal", factory)
    monkeypatch.setattr(worker_runtime, "get_extension_manager", _manager)
    monkeypatch.setattr(worker_runtime, "ensure_extension_deps_installed", _deps)
    monkeypatch.setattr(worker_runtime, "_extension_runtime_initialized", True)
    monkeypatch.setattr(worker_runtime, "_extension_runtime_generation", ())

    await worker_runtime._ensure_extension_runtime_for_task_process_async(
        required_extension_names={name}
    )
    assert visible_nodes[name] == "1.0.0"
    assert reload_count == 1

    # No extension change: the next task reuses the persistent child's registry.
    await worker_runtime._ensure_extension_runtime_for_task_process_async(
        required_extension_names={name}
    )
    assert reload_count == 1

    # Simulate install/update flow completing a newer runtime revision.
    with Session(test_db_engine) as session:
        current = session.exec(
            select(ExtensionRecord).where(ExtensionRecord.name == name)
        ).one()
        current.current_version = "2.0.0"
        current.installed_at = installed_at + timedelta(seconds=1)
        session.add(current)
        session.commit()

    await worker_runtime._ensure_extension_runtime_for_task_process_async(
        required_extension_names={name}
    )
    assert visible_nodes[name] == "2.0.0"
    assert reload_count == 2

    with Session(test_db_engine) as session:
        current = session.exec(
            select(ExtensionRecord).where(ExtensionRecord.name == name)
        ).one()
        session.delete(current)
        session.commit()
