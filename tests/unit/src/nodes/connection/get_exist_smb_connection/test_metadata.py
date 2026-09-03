from datetime import UTC, datetime

from db_connection.domain import ConnectionRecord

from src.node_dsl import SMBConnectionRecord
from src.nodes.connection import get_exist_smb_connection
from src.nodes.connection.get_exist_smb_connection import GetExistSMBConnection


def _make_node():
    return GetExistSMBConnection(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-1",
        connection_id="conn-1",
    )


def _make_connection_record() -> ConnectionRecord:
    return ConnectionRecord(
        id="conn-1",
        name="Shared files",
        kind="file",
        type="smbprotocol",
        driver=None,
        driver_options=None,
        properties={
            "host": "fileserver",
            "port": 445,
            "share": "shared",
            "username": "reader",
        },
        secrets={"password": "secret"},
        labels={},
        metadata={},
        extra={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_infer_metadata_uses_smb_loader(monkeypatch):
    calls = []
    expected = {"type": "SMB", "connection_id": "conn-1"}

    def fake_load_smb_metadata(**kwargs):
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(get_exist_smb_connection, "load_smb_metadata", fake_load_smb_metadata)

    node = _make_node()
    node.connection = SMBConnectionRecord(_make_connection_record())

    metadata = node.infer_metadata()

    assert metadata == {"connection": expected}
    assert calls == [{
        "connection_id": "conn-1",
        "host": "fileserver",
        "port": 445,
        "share": "shared",
        "username": "reader",
        "password": "secret",
    }]
