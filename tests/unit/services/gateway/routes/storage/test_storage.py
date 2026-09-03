from __future__ import annotations

from services.gateway.routes.storage.deps import get_file_storage_facade
from src.modules.file_storage.domain.entities import (
    DownloadedFile,
    StorageFileNode,
    StorageFolderNode,
    StorageTree,
)
from src.modules.file_storage.domain.types import StorageBackendKind
from src.modules.file_storage.flow.exceptions import UnsupportedTransferStrategyError


class _StubStorageFacade:
    def __init__(self) -> None:
        self.last_rename_kwargs = None
        self.last_move_kwargs = None

    async def list_nodes(self, *, path: str = "", max_items: int = 1000):
        return StorageTree(
            backend_kind=StorageBackendKind.SFTP,
            path=path,
            nodes=[
                StorageFolderNode(name="incoming", path="incoming", permissions="755"),
                StorageFileNode(name="report.csv", path="report.csv", size=12, permissions="644"),
            ],
            is_truncated=False,
            next_token=None,
        )

    async def generate_upload_presign(self, **kwargs):
        raise UnsupportedTransferStrategyError(StorageBackendKind.FTP.value, "Presigned upload")

    async def upload_file(self, **kwargs):
        return None

    async def download_file(self, **kwargs):
        return DownloadedFile(
            filename="report.csv",
            content=b"id,name\n1,Alice\n",
            media_type="text/csv",
        )

    async def rename_path(self, **kwargs):
        self.last_rename_kwargs = kwargs

    async def move_path(self, **kwargs):
        self.last_move_kwargs = kwargs


async def test_storage_list_route_supports_non_s3_nodes(gateway_client, router_prefix) -> None:
    from services.gateway.main import app

    app.dependency_overrides[get_file_storage_facade] = lambda: _StubStorageFacade()
    try:
        response = await gateway_client.get(
            f"{router_prefix}/storage/list",
            params={"connection_id": "conn-1", "path": ""},
        )
    finally:
        app.dependency_overrides.pop(get_file_storage_facade, None)

    assert response.status_code == 200
    payload = response.json()
    assert [node["name"] for node in payload["nodes"]] == ["incoming", "report.csv"]
    assert payload["nodes"][0]["path"] == "incoming"
    assert payload["nodes"][1]["size"] == 12


async def test_storage_upload_presign_route_returns_400_for_ftp(gateway_client, router_prefix) -> None:
    from services.gateway.main import app

    app.dependency_overrides[get_file_storage_facade] = lambda: _StubStorageFacade()
    try:
        response = await gateway_client.get(
            f"{router_prefix}/storage/upload/presign",
            params={
                "connection_id": "conn-1",
                "path": "",
                "filename": "report.csv",
                "content_type_prefix": "text/",
            },
        )
    finally:
        app.dependency_overrides.pop(get_file_storage_facade, None)

    assert response.status_code == 400
    assert "Presigned upload" in response.text


async def test_storage_download_proxy_streams_file(gateway_client, router_prefix) -> None:
    from services.gateway.main import app

    app.dependency_overrides[get_file_storage_facade] = lambda: _StubStorageFacade()
    try:
        response = await gateway_client.get(
            f"{router_prefix}/storage/download/file",
            params={
                "connection_id": "conn-1",
                "path": "",
                "filename": "report.csv",
            },
        )
    finally:
        app.dependency_overrides.pop(get_file_storage_facade, None)

    assert response.status_code == 200
    assert response.text == "id,name\n1,Alice\n"
    assert response.headers["content-disposition"] == 'attachment; filename="report.csv"'


async def test_storage_rename_route_calls_facade(gateway_client, router_prefix) -> None:
    from services.gateway.main import app

    storage = _StubStorageFacade()
    app.dependency_overrides[get_file_storage_facade] = lambda: storage
    try:
        response = await gateway_client.post(
            f"{router_prefix}/storage/path/rename",
            params={"connection_id": "conn-1"},
            json={"path": "incoming/report.csv", "new_name": "report-final.csv"},
        )
    finally:
        app.dependency_overrides.pop(get_file_storage_facade, None)

    assert response.status_code == 200
    assert storage.last_rename_kwargs == {
        "path": "incoming/report.csv",
        "new_name": "report-final.csv",
    }


async def test_storage_move_route_calls_facade(gateway_client, router_prefix) -> None:
    from services.gateway.main import app

    storage = _StubStorageFacade()
    app.dependency_overrides[get_file_storage_facade] = lambda: storage
    try:
        response = await gateway_client.post(
            f"{router_prefix}/storage/path/move",
            params={"connection_id": "conn-1"},
            json={"path": "incoming/report.csv", "target_path": "archive/2025"},
        )
    finally:
        app.dependency_overrides.pop(get_file_storage_facade, None)

    assert response.status_code == 200
    assert storage.last_move_kwargs == {
        "path": "incoming/report.csv",
        "target_path": "archive/2025",
    }
