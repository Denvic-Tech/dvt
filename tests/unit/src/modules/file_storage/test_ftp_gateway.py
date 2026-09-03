from __future__ import annotations

from ftplib import error_perm

from src.modules.file_storage.domain.types import StorageBackendKind
from src.modules.file_storage.flow.connections import ResolvedFTPStorageConnection
from src.modules.file_storage.infra.gateways.ftp import FTPFileStorageGateway


class _FakeFTPClient:
    def __init__(self) -> None:
        self.current_dir = "/home/ftpuser"

    def quit(self) -> None:
        return None

    def close(self) -> None:
        return None

    def pwd(self) -> str:
        return self.current_dir

    def cwd(self, path: str) -> None:
        if path in {"/home/ftpuser", "/home/ftpuser/incoming"}:
            self.current_dir = path
            return
        raise error_perm("550 Not a directory.")

    def mlsd(self, path: str):
        raise error_perm("500 Unknown command.")

    def nlst(self, path: str) -> list[str]:
        assert path == "/home/ftpuser"
        return ["/home/ftpuser/incoming", "/home/ftpuser/report.csv"]

    def size(self, path: str) -> int:
        assert path == "/home/ftpuser/report.csv"
        return 12

    def sendcmd(self, command: str) -> str:
        assert command == "MDTM /home/ftpuser/report.csv"
        return "213 20260515120000"


class _FakeFTPCreateErrorClient:
    def __init__(self) -> None:
        self.current_dir = "/"

    def quit(self) -> None:
        return None

    def close(self) -> None:
        return None

    def pwd(self) -> str:
        return self.current_dir

    def cwd(self, path: str) -> None:
        if path in {"/", "/mnt"}:
            self.current_dir = path
            return
        raise error_perm("550 Not a directory.")

    def mkd(self, path: str) -> None:
        raise error_perm(f"550 Permission denied: {path}")


def test_ftp_gateway_list_nodes_falls_back_when_mlsd_is_unsupported() -> None:
    connection = ResolvedFTPStorageConnection(
        client=_FakeFTPClient(),
        initial_directory="/home/ftpuser",
    )

    gateway = FTPFileStorageGateway(connection)
    tree = gateway.list_nodes(path="", max_items=1000)

    assert tree.backend_kind == StorageBackendKind.FTP
    assert tree.path == ""
    assert [node.name for node in tree.nodes] == ["incoming", "report.csv"]
    assert tree.nodes[0].path == "incoming"
    assert tree.nodes[1].path == "report.csv"
    assert tree.nodes[1].size == 12


def test_ftp_gateway_create_folder_raises_when_server_rejects_mkdir() -> None:
    connection = ResolvedFTPStorageConnection(
        client=_FakeFTPCreateErrorClient(),
        initial_directory="/",
    )

    gateway = FTPFileStorageGateway(connection)

    try:
        gateway.create_folder(path="mnt", folder_name="gfdh")
    except Exception as exc:  # noqa: BLE001
        assert "Failed to create FTP directory" in str(exc)
        assert "Permission denied" in str(exc)
    else:
        raise AssertionError("Expected create_folder to fail when FTP server rejects MKDIR")
