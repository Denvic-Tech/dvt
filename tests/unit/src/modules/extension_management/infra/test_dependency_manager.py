from types import SimpleNamespace

import pytest

from src.enums import ExtensionDepsStatus
from src.modules.extension_management.infra import dependency_manager as dependency_module
from src.modules.extension_management.infra.dependency_manager import (
    ExtensionDependencyManager,
)

import config


def test_gateway_extension_client_uses_configured_visibility_timeout() -> None:
    manager = ExtensionDependencyManager.create_with_celery()
    celery_client = manager._celery_client
    timeout = config.CELERY.CELERY_VISIBILITY_TIMEOUT_SEC

    assert celery_client is not None
    assert celery_client.conf.broker_transport_options["visibility_timeout"] == timeout
    assert celery_client.conf.result_backend_transport_options["visibility_timeout"] == timeout
    assert celery_client.conf.visibility_timeout == timeout


class _Result:
    def __init__(self, records):
        self._records = records

    def scalars(self):
        return SimpleNamespace(all=lambda: self._records)


class _Session:
    def __init__(self, records):
        self._records = records

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, _stmt):
        return _Result(self._records)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("record", "expected_fragment"),
    [
        (SimpleNamespace(name="ext", manifest_json={}, is_installed=True, is_enabled=True, deps_status=ExtensionDepsStatus.READY), None),
        (SimpleNamespace(name="ext", manifest_json={}, is_installed=True, is_enabled=True, deps_status=ExtensionDepsStatus.INSTALLING), "deps_installing"),
        (SimpleNamespace(name="ext", manifest_json={}, is_installed=True, is_enabled=True, deps_status=ExtensionDepsStatus.ERROR), "deps_error"),
        (SimpleNamespace(name="ext", manifest_json={}, is_installed=True, is_enabled=False, deps_status=ExtensionDepsStatus.READY), "disabled"),
        (SimpleNamespace(name="ext", manifest_json={}, is_installed=False, is_enabled=True, deps_status=ExtensionDepsStatus.NOT_INSTALLED), "not_installed"),
    ],
)
async def test_extension_availability_requires_executable_readiness(
    monkeypatch,
    record,
    expected_fragment,
):
    monkeypatch.setattr(
        dependency_module,
        "AsyncSessionLocal",
        lambda: _Session([record]),
    )

    missing, not_ready = await ExtensionDependencyManager().check_extensions_availability({"ext"})

    assert missing == []
    if expected_fragment is None:
        assert not_ready == []
    else:
        assert len(not_ready) == 1
        assert expected_fragment in not_ready[0]


@pytest.mark.asyncio
async def test_extension_availability_reports_missing(monkeypatch):
    monkeypatch.setattr(dependency_module, "AsyncSessionLocal", lambda: _Session([]))

    missing, not_ready = await ExtensionDependencyManager().check_extensions_availability({"missing"})

    assert missing == ["missing"]
    assert not_ready == []


@pytest.mark.asyncio
@pytest.mark.parametrize("publish_status", [False, True])
@pytest.mark.parametrize("returncode", [0, 1])
async def test_local_dependency_install_does_not_change_shared_readiness(
    async_test_db_engine, monkeypatch, tmp_path, publish_status, returncode,
):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlmodel import select

    from src.modules.extension_management.infra.db_models import ExtensionRecord

    factory = async_sessionmaker(async_test_db_engine, expire_on_commit=False)
    record = ExtensionRecord(
        name="deps-test", display_name="Deps", is_installed=True,
        deps_status=ExtensionDepsStatus.READY, install_path=str(tmp_path),
        manifest_json={"requirements": ["example-package==1.0"]},
    )
    async with factory() as session:
        session.add(record)
        await session.commit()
        await session.refresh(record)
        original_timestamp = record.updated_at

    monkeypatch.setattr(dependency_module, "AsyncSessionLocal", factory)
    transitions = []

    def run_pip(*_args, **_kwargs):
        return SimpleNamespace(returncode=returncode, stderr="install failed", stdout="")

    monkeypatch.setattr(dependency_module.subprocess, "run", run_pip)
    manager = ExtensionDependencyManager()
    update_status = manager.update_deps_status

    async def track_status(name, status):
        transitions.append(status)
        return await update_status(name, status)

    monkeypatch.setattr(manager, "update_deps_status", track_status)
    result = await manager.install_dependencies("deps-test", publish_status=publish_status)
    assert result.success is (returncode == 0)

    async with factory() as session:
        stored = (await session.execute(select(ExtensionRecord))).scalars().one()
        if publish_status:
            expected = ExtensionDepsStatus.READY if returncode == 0 else ExtensionDepsStatus.ERROR
            assert transitions == [ExtensionDepsStatus.INSTALLING, expected]
            assert stored.deps_status == expected
        else:
            assert transitions == []
            assert stored.deps_status == ExtensionDepsStatus.READY
            assert stored.updated_at == original_timestamp


@pytest.mark.asyncio
async def test_repeating_dependency_status_does_not_change_timestamp(
    async_test_db_engine, monkeypatch,
):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlmodel import select

    from src.modules.extension_management.infra.db_models import ExtensionRecord

    factory = async_sessionmaker(async_test_db_engine, expire_on_commit=False)
    async with factory() as session:
        record = ExtensionRecord(
            name="ready", display_name="Ready", deps_status=ExtensionDepsStatus.READY,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        timestamp = record.updated_at
    monkeypatch.setattr(dependency_module, "AsyncSessionLocal", factory)
    await ExtensionDependencyManager().update_deps_status("ready", ExtensionDepsStatus.READY)
    async with factory() as session:
        record = (await session.execute(select(ExtensionRecord))).scalars().one()
        assert record.updated_at == timestamp
