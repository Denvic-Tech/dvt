from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from db_connection import AccessDeniedError, ConnectionNotFoundError
from db_connection.domain import ConnectionRecord

from src.modules.db_connection.flow.use_cases import ResolvedConnectionClient
from src.node_dsl import SMBConnectionRecord
from src.nodes.connection.get_exist_smb_connection import node as get_exist_smb_connection
from src.nodes.connection.get_exist_smb_connection import GetExistSMBConnection


class FakeResolveUseCase:
    def __init__(self, *, resolved=None, exc=None):
        self._resolved = resolved
        self._exc = exc
        self.calls = []

    async def execute(self, *, connection_id: str, actor):
        self.calls.append({"connection_id": connection_id, "actor": actor})
        if self._exc is not None:
            raise self._exc
        return self._resolved


def _make_node():
    return GetExistSMBConnection(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-1",
        connection_id="conn-1",
    )


def _patch_user(monkeypatch, user):
    async def fake_get_user(self):
        return user

    monkeypatch.setattr(GetExistSMBConnection, "_get_user", fake_get_user)


def _make_connection_record(
    *,
    kind: str = "file",
    connection_type: str = "smbprotocol",
) -> ConnectionRecord:
    return ConnectionRecord(
        id="conn-1",
        name="Shared files",
        kind=kind,
        type=connection_type,
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


@pytest.mark.asyncio
async def test_process_sets_connection(monkeypatch):
    record = SMBConnectionRecord(_make_connection_record())

    async def fake_get_connection(self):
        return record

    monkeypatch.setattr(GetExistSMBConnection, "_get_connection_from_db", fake_get_connection)
    node = _make_node()
    await node.process()

    assert node.connection is record


@pytest.mark.asyncio
async def test_get_connection_from_db_loads_actor_and_uses_resolve_use_case(monkeypatch):
    user = SimpleNamespace(role="admin", id="user-1", organization_id="org-1")
    use_case = FakeResolveUseCase(
        resolved=ResolvedConnectionClient(
            client=object(),
            connection=_make_connection_record(),
            type="smbprotocol",
            kind="file",
            driver=None,
        )
    )

    _patch_user(monkeypatch, user)
    monkeypatch.setattr(
        get_exist_smb_connection,
        "build_resolve_connection_client_use_case",
        lambda **_kwargs: use_case,
    )

    node = _make_node()
    result_connection = await node._get_connection_from_db()

    assert isinstance(result_connection, SMBConnectionRecord)
    assert result_connection.record.id == "conn-1"
    assert result_connection.type == "smbprotocol"
    assert use_case.calls == [{"connection_id": "conn-1", "actor": user}]


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [ConnectionNotFoundError("conn-1"), AccessDeniedError("denied")])
async def test_get_connection_from_db_maps_access_errors_to_value_error(monkeypatch, exc):
    user = SimpleNamespace(role="user", id="user-1", organization_id="org-1")
    use_case = FakeResolveUseCase(exc=exc)
    log_calls = []

    _patch_user(monkeypatch, user)
    monkeypatch.setattr(
        get_exist_smb_connection,
        "build_resolve_connection_client_use_case",
        lambda **_kwargs: use_case,
    )
    monkeypatch.setattr(get_exist_smb_connection.logger, "error", log_calls.append)

    node = _make_node()

    with pytest.raises(ValueError, match="No DB connection found"):
        await node._get_connection_from_db()

    assert log_calls


@pytest.mark.asyncio
async def test_get_connection_from_db_rejects_non_smb_connection(monkeypatch):
    user = SimpleNamespace(role="admin", id="user-1", organization_id="org-1")
    use_case = FakeResolveUseCase(
        resolved=ResolvedConnectionClient(
            client=object(),
            connection=_make_connection_record(connection_type="ftp"),
            type="ftp",
            kind="file",
            driver=None,
        )
    )
    log_calls = []

    _patch_user(monkeypatch, user)
    monkeypatch.setattr(
        get_exist_smb_connection,
        "build_resolve_connection_client_use_case",
        lambda **_kwargs: use_case,
    )
    monkeypatch.setattr(get_exist_smb_connection.logger, "error", log_calls.append)

    node = _make_node()

    with pytest.raises(TypeError, match="is not a SMB connection"):
        await node._get_connection_from_db()

    assert log_calls[-1] == "Connection with ID conn-1 is not a SMB connection."


@pytest.mark.asyncio
async def test_get_connection_from_db_raises_when_user_missing(monkeypatch):
    log_calls = []

    _patch_user(monkeypatch, None)
    monkeypatch.setattr(get_exist_smb_connection.logger, "error", log_calls.append)

    node = _make_node()

    with pytest.raises(ValueError, match="No DB connection found"):
        await node._get_connection_from_db()

    assert log_calls
