from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from src.models.extension import ExtensionRecord


@pytest.mark.asyncio
async def test_list_extensions(
        gateway_client,
        router_prefix,
        db_session,
):
    """Тест получения списка всех расширений"""
    # Создаем тестовое расширение
    extension = ExtensionRecord(
        name="test-extension",
        display_name="Test Extension",
        description="test description",
        repository_url="https://example.com/repo.git",
        is_enabled=True,
        is_installed=True,
        install_path="/tmp/test",
        manifest_json={},
        state_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(extension)
    db_session.commit()

    response = await gateway_client.get(f"{router_prefix}/extensions")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # Проверяем, что наше тестовое расширение есть в списке
    extension_names = [item["name"] for item in data]
    assert "test-extension" in extension_names


@pytest.mark.asyncio
async def test_get_extension_frontend_not_installed(
        gateway_client,
        router_prefix,
        db_session,
):
    """Тест получения фронтенд метаданных для неустановленного расширения"""
    response = await gateway_client.get(f"{router_prefix}/extensions/non-existent/frontend")

    assert response.status_code == 404
    assert "not found" in response.json()["description"].lower()


@pytest.mark.asyncio
async def test_get_extension_frontend_asset_not_found(
        gateway_client,
        router_prefix,
        db_session,
        tmp_path,
):
    """Тест получения несуществующего ассета фронтенда"""
    install_dir = tmp_path / "extensions" / "test-extension"
    install_dir.mkdir(parents=True)

    extension = ExtensionRecord(
        name="test-extension",
        display_name="Test Extension",
        is_enabled=True,
        is_installed=True,
        install_path=str(install_dir),
        manifest_json={},
        state_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(extension)
    db_session.commit()

    response = await gateway_client.get(
        f"{router_prefix}/extensions/test-extension/frontend/assets/non-existent.js"
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_install_extension(
        gateway_client,
        router_prefix,
        db_session,
        tmp_path,
):
    """Тест установки расширения"""
    extension = ExtensionRecord(
        name="test-extension",
        display_name="Test Extension",
        description="test description",
        repository_url="https://example.com/repo.git",
        is_enabled=True,
        is_installed=False,
        install_path=None,
        manifest_json={},
        state_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(extension)
    db_session.commit()
    with patch('src.managers.extension_manager.ExtensionManager.install_extension') as mock_install:
        mock_install.return_value = ExtensionRecord(
            name="test-extension",
            display_name="Test Extension",
            description="test description",
            repository_url="https://example.com/repo.git",
            is_enabled=True,
            is_installed=True,
            install_path=str(tmp_path / "extensions" / "test-extension"),
            manifest_json={},
            state_json={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        response = await gateway_client.post(f"{router_prefix}/extensions/test-extension/install")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test-extension"
        assert data["is_installed"] is True
        mock_install.assert_awaited_once_with("test-extension", version=None)


@pytest.mark.asyncio
async def test_install_extension_with_version_query(
        gateway_client,
        router_prefix,
        db_session,
        tmp_path,
):
    extension = ExtensionRecord(
        name="test-extension",
        display_name="Test Extension",
        description="test description",
        repository_url="https://example.com/repo.git",
        is_enabled=True,
        is_installed=False,
        install_path=None,
        manifest_json={},
        state_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(extension)
    db_session.commit()
    with patch('src.managers.extension_manager.ExtensionManager.install_extension') as mock_install:
        mock_install.return_value = ExtensionRecord(
            name="test-extension",
            display_name="Test Extension",
            description="test description",
            repository_url="https://example.com/repo.git",
            is_enabled=True,
            is_installed=True,
            install_path=str(tmp_path / "extensions" / "test-extension"),
            manifest_json={},
            state_json={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        response = await gateway_client.post(
            f"{router_prefix}/extensions/test-extension/install?version=1.2.3"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test-extension"
        assert data["is_installed"] is True
        mock_install.assert_awaited_once_with("test-extension", version="1.2.3")


@pytest.mark.asyncio
async def test_uninstall_extension(
        gateway_client,
        router_prefix,
        db_session,
        tmp_path,
):
    """Тест удаления файлов расширения"""
    install_dir = tmp_path / "extensions" / "test-extension"
    install_dir.mkdir(parents=True)

    extension = ExtensionRecord(
        name="test-extension",
        display_name="Test Extension",
        is_enabled=True,
        is_installed=True,
        install_path=str(install_dir),
        manifest_json={},
        state_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(extension)
    db_session.commit()

    with patch('src.managers.extension_manager.ExtensionManager.uninstall_extension') as mock_uninstall:
        mock_uninstall.return_value = extension

        response = await gateway_client.delete(f"{router_prefix}/extensions/test-extension/uninstall")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test-extension"


@pytest.mark.asyncio
async def test_reload_extension(
        gateway_client,
        router_prefix,
        db_session,
):
    """Тест перезагрузки расширения"""
    extension = ExtensionRecord(
        name="test-extension",
        display_name="Test Extension",
        is_enabled=True,
        is_installed=True,
        install_path="/tmp/test",
        manifest_json={},
        state_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(extension)
    db_session.commit()

    with patch('src.managers.extension_manager.ExtensionManager.reload_extension') as mock_reload:
        mock_reload.return_value = extension

        response = await gateway_client.post(f"{router_prefix}/extensions/test-extension/reload")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test-extension"


@pytest.mark.asyncio
async def test_enable_extension(
        gateway_client,
        router_prefix,
        db_session,
):
    """Тест включения расширения"""
    extension = ExtensionRecord(
        name="test-extension",
        display_name="Test Extension",
        is_enabled=False,
        is_installed=True,
        install_path="/tmp/test",
        manifest_json={},
        state_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(extension)
    db_session.commit()

    with patch('src.managers.extension_manager.ExtensionManager.set_enabled') as mock_enable:
        extension.is_enabled = True
        mock_enable.return_value = extension

        response = await gateway_client.post(f"{router_prefix}/extensions/test-extension/enable")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test-extension"
        assert data["is_enabled"] is True


@pytest.mark.asyncio
async def test_disable_extension(
        gateway_client,
        router_prefix,
        db_session,
):
    """Тест отключения расширения"""
    extension = ExtensionRecord(
        name="test-extension",
        display_name="Test Extension",
        is_enabled=True,
        is_installed=True,
        install_path="/tmp/test",
        manifest_json={},
        state_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(extension)
    db_session.commit()

    with patch('src.managers.extension_manager.ExtensionManager.set_enabled') as mock_disable:
        extension.is_enabled = False
        mock_disable.return_value = extension

        response = await gateway_client.post(f"{router_prefix}/extensions/test-extension/disable")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test-extension"
        assert data["is_enabled"] is False
