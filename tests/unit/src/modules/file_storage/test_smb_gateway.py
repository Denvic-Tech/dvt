from __future__ import annotations

import io
import stat
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.modules.file_storage.domain.types import StorageBackendKind
from src.modules.file_storage.flow.connections import ResolvedSMBStorageConnection
from src.modules.file_storage.flow.exceptions import UnsupportedTransferStrategyError
from src.modules.file_storage.infra.gateways.smb import SMBFileStorageGateway


class _FakeSMBDirEntry:
    def __init__(
        self,
        name: str,
        *,
        is_dir: bool,
        mode: int,
        size: int = 0,
        mtime: float | datetime | None = None,
    ) -> None:
        self.name = name
        self._is_dir = is_dir
        self.smb_info = SimpleNamespace(
            file_attributes=(
                SMBFileStorageGateway._FILE_ATTRIBUTE_DIRECTORY
                if is_dir
                else getattr(stat, "FILE_ATTRIBUTE_NORMAL", 0x80)
            ),
            end_of_file=size,
            last_write_time=mtime,
            permissions=oct(mode & 0o777),
        )

    def is_dir(self) -> bool:
        return self._is_dir

    def stat(self):
        raise AssertionError("list_nodes should not call SMB DirEntry.stat()")


class _FakeSMBListClient:
    def scandir(self, path: str | None):
        assert path == "share/root"
        return [
            _FakeSMBDirEntry(name="incoming", is_dir=True, mode=stat.S_IFDIR | 0o755),
            _FakeSMBDirEntry(
                name="report.csv",
                is_dir=False,
                mode=stat.S_IFREG | 0o644,
                size=12,
                mtime=datetime(2026, 6, 1, tzinfo=UTC),
            ),
        ]


class _FakeSMBCreateErrorClient:
    def stat(self, path: str | None):
        if path == "mnt":
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755)
        raise FileNotFoundError(path)

    def mkdir(self, path: str | None) -> None:
        raise PermissionError(f"Permission denied: {path}")


class _FakeSMBStatAccessDeniedClient:
    def __init__(self) -> None:
        self.mkdir_calls: list[str | None] = []

    def stat(self, path: str | None):
        raise PermissionError(f"Permission denied while stating: {path}")

    def mkdir(self, path: str | None) -> None:
        self.mkdir_calls.append(path)


class _FakeSMBRenameClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    def rename(self, **kwargs) -> None:
        self.calls.append(kwargs)


class _FakeSMBDeleteFilesClient:
    def remove(self, *, path: str | None, filename: str) -> None:
        if filename == "bad.txt":
            raise PermissionError("blocked")


class _FakeSMBDeleteFolderClient:
    def __init__(self) -> None:
        self.removed_files: list[tuple[str | None, str]] = []
        self.removed_dirs: list[str | None] = []

    def scandir(self, path: str | None):
        tree = {
            "root/archive": [
                _FakeSMBDirEntry(name="nested", is_dir=True, mode=stat.S_IFDIR | 0o755),
                _FakeSMBDirEntry(name="report.csv", is_dir=False, mode=stat.S_IFREG | 0o644, size=12),
            ],
            "root/archive/nested": [
                _FakeSMBDirEntry(name="child.txt", is_dir=False, mode=stat.S_IFREG | 0o644, size=3),
            ],
        }
        return tree.get(path, [])

    def remove(self, *, path: str | None, filename: str) -> None:
        self.removed_files.append((path, filename))

    def rmdir(self, path: str | None) -> None:
        self.removed_dirs.append(path)


class _FakeSMBOpenFileClient:
    def __init__(self) -> None:
        self.files: dict[tuple[str | None, str], bytes] = {}
        self.directories = {"uploads"}

    def stat(self, path: str | None):
        if path in self.directories:
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755)
        raise FileNotFoundError(path)

    def mkdir(self, path: str | None) -> None:
        if path is not None:
            self.directories.add(path)

    @contextmanager
    def open_file(self, *, path: str | None, filename: str, mode: str):
        key = (path, filename)
        if mode == "wb":
            buffer = io.BytesIO()
            try:
                yield buffer
            finally:
                self.files[key] = buffer.getvalue()
            return

        yield io.BytesIO(self.files[key])


def test_smb_gateway_list_nodes_returns_non_s3_tree() -> None:
    gateway = SMBFileStorageGateway(
        ResolvedSMBStorageConnection(
            client=_FakeSMBListClient(),
            initial_directory="/share/root",
        )
    )

    tree = gateway.list_nodes(path="", max_items=1000)

    assert tree.backend_kind == StorageBackendKind.SMB
    assert tree.path == ""
    assert [node.name for node in tree.nodes] == ["incoming", "report.csv"]
    assert tree.nodes[0].path == "incoming"
    assert tree.nodes[0].permissions == "0o755"
    assert tree.nodes[1].path == "report.csv"
    assert tree.nodes[1].size == 12
    assert tree.nodes[1].permissions == "0o644"


def test_smb_gateway_create_folder_raises_when_server_rejects_mkdir() -> None:
    gateway = SMBFileStorageGateway(
        ResolvedSMBStorageConnection(
            client=_FakeSMBCreateErrorClient(),
            initial_directory="/",
        )
    )

    with pytest.raises(Exception) as exc_info:  # noqa: BLE001
        gateway.create_folder(path="mnt", folder_name="restricted")

    assert "Failed to create SMB directory" in str(exc_info.value)
    assert "Permission denied" in str(exc_info.value)


def test_smb_gateway_create_folder_does_not_treat_access_denied_stat_as_missing_directory() -> None:
    client = _FakeSMBStatAccessDeniedClient()
    gateway = SMBFileStorageGateway(
        ResolvedSMBStorageConnection(
            client=client,
            initial_directory="/",
        )
    )

    with pytest.raises(Exception) as exc_info:  # noqa: BLE001
        gateway.create_folder(path="", folder_name="restricted")

    assert "Failed to create SMB directory" in str(exc_info.value)
    assert "Permission denied while stating" in str(exc_info.value)
    assert client.mkdir_calls == []


def test_smb_gateway_rename_and_move_delegate_to_client_rename() -> None:
    client = _FakeSMBRenameClient()
    gateway = SMBFileStorageGateway(
        ResolvedSMBStorageConnection(
            client=client,
            initial_directory="/root",
        )
    )

    gateway.rename_path(path="incoming/report.csv", new_name="report-final.csv")
    gateway.move_path(path="incoming/report-final.csv", target_path="archive/2026")

    assert client.calls == [
        {
            "src_path": "root/incoming",
            "src_filename": "report.csv",
            "dst_path": "root/incoming",
            "dst_filename": "report-final.csv",
        },
        {
            "src_path": "root/incoming",
            "src_filename": "report-final.csv",
            "dst_path": "root/archive/2026",
            "dst_filename": "report-final.csv",
        },
    ]


def test_smb_gateway_delete_files_returns_partial_success() -> None:
    gateway = SMBFileStorageGateway(
        ResolvedSMBStorageConnection(
            client=_FakeSMBDeleteFilesClient(),
            initial_directory="/root",
        )
    )

    result = gateway.delete_files(paths=["ok.txt", "bad.txt"])

    assert result.deleted_count == 1
    assert result.errors == ["bad.txt: blocked"]


def test_smb_gateway_delete_folder_recursively_removes_tree() -> None:
    client = _FakeSMBDeleteFolderClient()
    gateway = SMBFileStorageGateway(
        ResolvedSMBStorageConnection(
            client=client,
            initial_directory="/root",
        )
    )

    result = gateway.delete_folder(path="archive")

    assert result.deleted_count == 2
    assert result.errors == []
    assert client.removed_files == [
        ("root/archive/nested", "child.txt"),
        ("root/archive", "report.csv"),
    ]
    assert client.removed_dirs == ["root/archive/nested", "root/archive"]


def test_smb_gateway_upload_and_download_file_round_trip() -> None:
    client = _FakeSMBOpenFileClient()
    gateway = SMBFileStorageGateway(
        ResolvedSMBStorageConnection(
            client=client,
            initial_directory="/uploads",
        )
    )

    gateway.upload_file(
        path="incoming/2026",
        filename="report.csv",
        content=b"id,name\n1,Alice\n",
    )
    downloaded = gateway.download_file(path="incoming/2026", filename="report.csv")

    assert client.files[("uploads/incoming/2026", "report.csv")] == b"id,name\n1,Alice\n"
    assert downloaded.filename == "report.csv"
    assert downloaded.content == b"id,name\n1,Alice\n"
    # assert downloaded.media_type == "text/csv"
    # TODO: need fix ↑


def test_smb_gateway_presign_methods_are_not_supported() -> None:
    gateway = SMBFileStorageGateway(
        ResolvedSMBStorageConnection(
            client=object(),
            initial_directory="/",
        )
    )

    with pytest.raises(UnsupportedTransferStrategyError, match="Presigned upload"):
        gateway.generate_upload_presign()
    with pytest.raises(UnsupportedTransferStrategyError, match="Presigned download"):
        gateway.generate_download_presign()
