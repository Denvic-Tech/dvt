from types import SimpleNamespace

import pytest

import config
from src.enums import ExtensionDepsStatus
from src.managers import extension_dependency_manager as dependency_module
from src.managers.extension_dependency_manager import ExtensionDependencyManager


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
        (SimpleNamespace(name="ext", is_installed=True, is_enabled=True, deps_status=ExtensionDepsStatus.READY), None),
        (SimpleNamespace(name="ext", is_installed=True, is_enabled=True, deps_status=ExtensionDepsStatus.INSTALLING), "deps_installing"),
        (SimpleNamespace(name="ext", is_installed=True, is_enabled=True, deps_status=ExtensionDepsStatus.ERROR), "deps_error"),
        (SimpleNamespace(name="ext", is_installed=True, is_enabled=False, deps_status=ExtensionDepsStatus.READY), "disabled"),
        (SimpleNamespace(name="ext", is_installed=False, is_enabled=True, deps_status=ExtensionDepsStatus.NOT_INSTALLED), "not_installed"),
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
