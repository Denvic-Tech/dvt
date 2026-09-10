from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI

from services.gateway import lifespan as lifespan_module


class _AsyncSessionContext:
    def __init__(self, session: object) -> None:
        self.session = session

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _SyncSessionContext:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _StopAfterExtensionSync(RuntimeError):
    pass


@pytest.mark.asyncio
async def test_lifespan_uses_shared_async_session_factory(monkeypatch) -> None:
    app_settings_session = SimpleNamespace(commit=AsyncMock())
    extension_session = object()
    sessions = iter((app_settings_session, extension_session))
    async_session_local = Mock(
        side_effect=lambda: _AsyncSessionContext(next(sessions))
    )

    ensure_setting_value = AsyncMock()
    ensure_extension_deps_installed = AsyncMock()
    sync_installed_extensions = AsyncMock()
    distributor_client = SimpleNamespace(aclose=AsyncMock())
    extension_manager = SimpleNamespace(
        sync_installed_extensions=sync_installed_extensions
    )
    extension_manager_factory = Mock(return_value=extension_manager)

    monkeypatch.setattr(lifespan_module.config.AI_MCP, "validate", Mock())
    monkeypatch.setattr(
        lifespan_module,
        "Session",
        Mock(return_value=_SyncSessionContext()),
    )
    monkeypatch.setattr(lifespan_module, "wait_for_db", Mock())
    monkeypatch.setattr(lifespan_module, "AsyncSessionLocal", async_session_local)
    monkeypatch.setattr(
        lifespan_module.app_settings_helpers,
        "ensure_setting_value",
        ensure_setting_value,
    )
    monkeypatch.setattr(
        lifespan_module,
        "ensure_extension_deps_installed",
        ensure_extension_deps_installed,
    )
    monkeypatch.setattr(
        lifespan_module,
        "DenvicExtensionsDistributor",
        Mock(return_value=distributor_client),
    )
    monkeypatch.setattr(
        lifespan_module,
        "ExtensionManager",
        extension_manager_factory,
    )
    monkeypatch.setattr(
        lifespan_module.asyncio,
        "get_running_loop",
        Mock(side_effect=_StopAfterExtensionSync),
    )

    with pytest.raises(_StopAfterExtensionSync):
        async with lifespan_module.lifespan(FastAPI()):
            pass

    assert async_session_local.call_count == 2
    assert ensure_setting_value.await_args.kwargs["session"] is app_settings_session
    app_settings_session.commit.assert_awaited_once_with()
    ensure_extension_deps_installed.assert_awaited_once_with()
    extension_manager_factory.assert_called_once_with(
        extension_session,
        distributor_client,
        gateway_runtime=True,
    )
    sync_installed_extensions.assert_awaited_once_with()
    distributor_client.aclose.assert_awaited_once_with()
