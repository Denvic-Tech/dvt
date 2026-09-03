from datetime import UTC, datetime

import pytest

from src.models.extension import ExtensionRecord


@pytest.mark.asyncio
async def test_get_extension_frontend_returns_metadata(
    gateway_client,
    router_prefix,
    db_session,
    tmp_path,
):
    install_dir = tmp_path / "extensions" / "sample-extension"
    bundle_path = install_dir / "frontend" / "dist" / "index.js"
    bundle_path.parent.mkdir(parents=True)
    bundle_path.write_text("export function register() {}", encoding="utf-8")

    extension = ExtensionRecord(
        name="sample-extension",
        display_name="Sample Extension",
        description="test extension",
        repository_url="https://example.com/repo.git",
        is_enabled=True,
        is_installed=True,
        install_path=str(install_dir),
        manifest_json={
            "name": "sample-extension",
            "version": "0.1.0",
            "frontend": {
                "dist_dir": "frontend/dist",
                "entry_file": "index.js",
                "entrypoint": "register",
            },
        },
        state_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(extension)
    db_session.commit()

    response = await gateway_client.get(f"{router_prefix}/extensions/{extension.name}/frontend")

    assert response.status_code == 200
    assert response.json() == {
        "extension_name": "sample-extension",
        "installed": True,
        "bundle_url": "/api/extensions/sample-extension/frontend/assets/index.js",
        "entry_file": "index.js",
        "entrypoint": "register",
    }


@pytest.mark.asyncio
async def test_get_extension_frontend_asset_returns_bundle_content(
    gateway_client,
    router_prefix,
    db_session,
    tmp_path,
):
    install_dir = tmp_path / "extensions" / "sample-extension"
    bundle_path = install_dir / "frontend" / "dist" / "index.js"
    bundle_path.parent.mkdir(parents=True)
    bundle_content = "export function register() { return {}; }"
    bundle_path.write_text(bundle_content, encoding="utf-8")

    extension = ExtensionRecord(
        name="sample-extension",
        display_name="Sample Extension",
        description="test extension",
        repository_url="https://example.com/repo.git",
        is_enabled=True,
        is_installed=True,
        install_path=str(install_dir),
        manifest_json={
            "name": "sample-extension",
            "version": "0.1.0",
            "frontend": {
                "dist_dir": "frontend/dist",
                "entry_file": "index.js",
                "entrypoint": "register",
            },
        },
        state_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(extension)
    db_session.commit()

    response = await gateway_client.get(
        f"{router_prefix}/extensions/{extension.name}/frontend/assets/index.js"
    )

    assert response.status_code == 200
    assert response.text == bundle_content


@pytest.mark.asyncio
async def test_get_extension_frontend_asset_rejects_path_escape(
    gateway_client,
    router_prefix,
    db_session,
    tmp_path,
):
    install_dir = tmp_path / "extensions" / "sample-extension"
    bundle_path = install_dir / "frontend" / "dist" / "index.js"
    bundle_path.parent.mkdir(parents=True)
    bundle_path.write_text("export function register() {}", encoding="utf-8")

    extension = ExtensionRecord(
        name="sample-extension",
        display_name="Sample Extension",
        description="test extension",
        repository_url="https://example.com/repo.git",
        is_enabled=True,
        is_installed=True,
        install_path=str(install_dir),
        manifest_json={
            "name": "sample-extension",
            "version": "0.1.0",
            "frontend": {
                "dist_dir": "frontend/dist",
                "entry_file": "index.js",
                "entrypoint": "register",
            },
        },
        state_json={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(extension)
    db_session.commit()

    response = await gateway_client.get(
        f"{router_prefix}/extensions/{extension.name}/frontend/assets/..%2Fsecret.txt"
    )

    assert response.status_code == 400
