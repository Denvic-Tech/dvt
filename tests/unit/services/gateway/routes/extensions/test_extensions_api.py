"""
Полные тесты API /api/extensions.

Покрывают каждый эндпоинт: happy path + доступ не-superadmin пользователей.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.models.extension import ExtensionRecord


def _deny_superadmin_access():
    """Переопределяет superadmin-зависимость так, чтобы она выбрасывала 403."""
    from usrak.core.exceptions import AccessDeniedException

    from services.gateway.main import app

    from src.modules.user.infra.fastapi.dependencies import get_user_superadmin_access_only

    app.dependency_overrides[get_user_superadmin_access_only] = lambda: (_ for _ in ()).throw(
        AccessDeniedException()
    )


@pytest.mark.asyncio
async def test_sync_extensions(gateway_client, router_prefix):
    with patch(
        "src.managers.extension_manager.ExtensionManager.sync_available_extensions"
    ) as mock_sync:
        mock_sync.return_value = []
        response = await gateway_client.post(f"{router_prefix}/extensions/sync")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_sync_extensions_not_superadmin(gateway_client, router_prefix):
    _deny_superadmin_access()
    response = await gateway_client.post(f"{router_prefix}/extensions/sync")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_extensions_serializes_record(gateway_client, router_prefix):
    extension = ExtensionRecord(
        name="test-ext",
        display_name="Test Extension",
        is_enabled=True,
        is_installed=False,
        manifest_json={},
        state_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    with patch(
        "src.managers.extension_manager.ExtensionManager.list_extensions",
        new=AsyncMock(return_value=[extension]),
    ):
        response = await gateway_client.get(f"{router_prefix}/extensions")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "test-ext"


@pytest.mark.asyncio
async def test_list_extensions_not_superadmin(gateway_client, router_prefix):
    _deny_superadmin_access()
    response = await gateway_client.get(f"{router_prefix}/extensions")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_frontend_unauthenticated(
    unauthenticated_gateway_client, router_prefix, db_session, tmp_path
):
    """Эндпоинт фронтенда публичный — работает без аутентификации."""
    install_dir = tmp_path / "extensions" / "public-ext"
    bundle_path = install_dir / "frontend" / "dist" / "index.js"
    bundle_path.parent.mkdir(parents=True)
    bundle_path.write_text("export default {}", encoding="utf-8")

    extension = ExtensionRecord(
        name="public-ext",
        display_name="Public Extension",
        is_enabled=True,
        is_installed=True,
        install_path=str(install_dir),
        manifest_json={
            "name": "public-ext",
            "version": "1.0.0",
            "frontend": {"dist_dir": "frontend/dist", "entry_file": "index.js"},
        },
        state_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(extension)
    db_session.commit()

    response = await unauthenticated_gateway_client.get(
        f"{router_prefix}/extensions/public-ext/frontend"
    )
    assert response.status_code == 200
    assert response.json()["extension_name"] == "public-ext"


@pytest.mark.asyncio
async def test_get_frontend_asset_unauthenticated(
    unauthenticated_gateway_client, router_prefix, db_session, tmp_path
):
    """Ассеты фронтенда публичны."""
    install_dir = tmp_path / "extensions" / "public-ext"
    bundle_path = install_dir / "frontend" / "dist" / "app.js"
    bundle_path.parent.mkdir(parents=True)
    bundle_path.write_text("console.log('hello')", encoding="utf-8")

    extension = ExtensionRecord(
        name="public-ext",
        display_name="Public Extension",
        is_enabled=True,
        is_installed=True,
        install_path=str(install_dir),
        manifest_json={
            "name": "public-ext",
            "version": "1.0.0",
            "frontend": {"dist_dir": "frontend/dist", "entry_file": "app.js"},
        },
        state_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(extension)
    db_session.commit()

    response = await unauthenticated_gateway_client.get(
        f"{router_prefix}/extensions/public-ext/frontend/assets/app.js"
    )
    assert response.status_code == 200
    assert response.text == "console.log('hello')"


@pytest.mark.asyncio
async def test_install_extension_not_found(gateway_client, router_prefix):
    with patch(
        "src.managers.extension_manager.ExtensionManager.install_extension",
        side_effect=ValueError("Extension 'unknown' not found."),
    ):
        response = await gateway_client.post(f"{router_prefix}/extensions/unknown/install")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_install_extension_not_superadmin(gateway_client, router_prefix):
    _deny_superadmin_access()
    response = await gateway_client.post(f"{router_prefix}/extensions/test-ext/install")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_uninstall_extension_not_superadmin(gateway_client, router_prefix):
    _deny_superadmin_access()
    response = await gateway_client.delete(f"{router_prefix}/extensions/test-ext/uninstall")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reload_extension_not_superadmin(gateway_client, router_prefix):
    _deny_superadmin_access()
    response = await gateway_client.post(f"{router_prefix}/extensions/test-ext/reload")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_enable_extension_not_superadmin(gateway_client, router_prefix):
    _deny_superadmin_access()
    response = await gateway_client.post(f"{router_prefix}/extensions/test-ext/enable")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_disable_extension_not_found(gateway_client, router_prefix):
    with patch(
        "src.managers.extension_manager.ExtensionManager.set_enabled",
        side_effect=ValueError("Extension 'unknown' not found."),
    ):
        response = await gateway_client.post(f"{router_prefix}/extensions/unknown/disable")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_disable_extension_not_superadmin(gateway_client, router_prefix):
    _deny_superadmin_access()
    response = await gateway_client.post(f"{router_prefix}/extensions/test-ext/disable")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_extension_state(gateway_client, router_prefix):
    with patch(
        "src.managers.extension_state_manager.ExtensionStateManager.async_get_state"
    ) as mock_get_state:
        mock_get_state.return_value = {"last_run": "2025-01-01"}
        response = await gateway_client.get(f"{router_prefix}/extensions/test-ext/state")
        assert response.status_code == 200
        data = response.json()
        assert data["extension_name"] == "test-ext"
        assert data["state_key"] == "default"
        assert data["value"] == {"last_run": "2025-01-01"}


@pytest.mark.asyncio
async def test_get_extension_state_with_key(gateway_client, router_prefix):
    with patch(
        "src.managers.extension_state_manager.ExtensionStateManager.async_get_state"
    ) as mock_get_state:
        mock_get_state.return_value = {"cursor": 42}
        response = await gateway_client.get(
            f"{router_prefix}/extensions/test-ext/state?key=cursors"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["state_key"] == "cursors"
        assert data["value"] == {"cursor": 42}


@pytest.mark.asyncio
async def test_get_extension_state_regular_user(gateway_client, router_prefix, test_admin_user):
    """GET /state доступен НЕ-superadmin пользователям."""
    from services.gateway.main import app

    from src.modules.user.infra.fastapi.dependencies import get_user_access_only

    app.dependency_overrides[get_user_access_only] = lambda: test_admin_user

    with patch(
        "src.managers.extension_state_manager.ExtensionStateManager.async_get_state"
    ) as mock_get_state:
        mock_get_state.return_value = {}
        response = await gateway_client.get(f"{router_prefix}/extensions/test-ext/state")
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_extension_state(gateway_client, router_prefix):
    with patch(
        "src.managers.extension_state_manager.ExtensionStateManager.async_set_state"
    ) as mock_set_state:
        mock_set_state.return_value = {"saved": True}
        response = await gateway_client.put(
            f"{router_prefix}/extensions/test-ext/state",
            json={"value": {"saved": True}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["extension_name"] == "test-ext"
        assert data["state_key"] == "default"
        assert data["value"] == {"saved": True}


@pytest.mark.asyncio
async def test_update_extension_state_regular_user(gateway_client, router_prefix, test_admin_user):
    """PUT /state доступен НЕ-superadmin пользователям."""
    from services.gateway.main import app

    from src.modules.user.infra.fastapi.dependencies import get_user_access_only

    app.dependency_overrides[get_user_access_only] = lambda: test_admin_user

    with patch(
        "src.managers.extension_state_manager.ExtensionStateManager.async_set_state"
    ) as mock_set_state:
        mock_set_state.return_value = {"updated": True}
        response = await gateway_client.put(
            f"{router_prefix}/extensions/test-ext/state",
            json={"value": {"updated": True}},
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_reload_installed_extensions(gateway_client, router_prefix):
    with patch(
        "src.managers.extension_manager.ExtensionManager.sync_installed_extensions"
    ) as mock_reload:
        mock_reload.return_value = []
        response = await gateway_client.post(f"{router_prefix}/extensions/reload-installed")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "перезагружены" in data["message"]


@pytest.mark.asyncio
async def test_reload_installed_extensions_not_superadmin(gateway_client, router_prefix):
    _deny_superadmin_access()
    response = await gateway_client.post(f"{router_prefix}/extensions/reload-installed")
    assert response.status_code == 403
