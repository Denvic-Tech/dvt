from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from db_connection import AccessDeniedError, ConnectionNotFoundError
from db_connection.domain import ConnectionRecord

from src.modules.user.infra import db_models
from src.node_dsl import SqlConnectionRecord
from src.nodes.connection.get_exist_db_connection import node as get_exist_db_connection
from src.nodes.connection.get_exist_db_connection import GetExistDBConnection


class FakeSelect:
    def __init__(self, model):
        self.model = model
        self.where_args = []
        self.limit_value = None

    def where(self, *args):
        self.where_args.extend(args)
        return self

    def limit(self, value):
        self.limit_value = value
        return self


class FakeResult:
    def __init__(self, value=None):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value


class FakeAsyncSession:
    def __init__(self, _engine, user):
        self._user = user
        self.executed_models = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement):
        self.executed_models.append(statement.model)
        if statement.model is db_models.UserRecord:
            return FakeResult(self._user)
        raise AssertionError("Unexpected statement model")


class FakeConnectionService:
    def __init__(self, *, record=None, exc=None):
        self._record = record
        self._exc = exc
        self.calls = []

    async def get(self, connection_id: str, *, actor):
        self.calls.append({"connection_id": connection_id, "actor": actor})
        if self._exc is not None:
            raise self._exc
        return self._record


def _make_node():
    return GetExistDBConnection(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-1",
        connection_id="conn-1",
    )


def _patch_user(monkeypatch, user):
    async def fake_get_user(self):
        return user

    monkeypatch.setattr(GetExistDBConnection, "_get_user", fake_get_user)


def _make_connection_record(*, kind: str = "sql", connection_type: str = "sqlite") -> ConnectionRecord:
    return ConnectionRecord(
        id="conn-1",
        name="Test connection",
        kind=kind,
        type=connection_type,
        driver="pysqlite" if connection_type == "sqlite" else None,
        driver_options=None,
        properties={"database": ":memory:"} if connection_type == "sqlite" else {},
        secrets={},
        labels={},
        metadata={},
        extra={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_process_sets_connection(monkeypatch):
    record = SqlConnectionRecord(_make_connection_record())

    async def fake_get_connection(self):
        return record

    monkeypatch.setattr(GetExistDBConnection, "_get_connection_from_db", fake_get_connection)
    node = _make_node()
    await node.process()

    assert node.connection is record


@pytest.mark.asyncio
async def test_get_connection_from_db_loads_actor_and_uses_record_only_service(monkeypatch):
    user = SimpleNamespace(role="admin", id="user-1", organization_id="org-1")
    service = FakeConnectionService(record=_make_connection_record())

    _patch_user(monkeypatch, user)
    monkeypatch.setattr(
        get_exist_db_connection,
        "_build_connection_service",
        lambda: service,
    )

    node = _make_node()
    result_connection = await node._get_connection_from_db()

    assert isinstance(result_connection, SqlConnectionRecord)
    assert result_connection.record.id == "conn-1"
    assert result_connection.type == "sqlite"
    assert service.calls == [{"connection_id": "conn-1", "actor": user}]


@pytest.mark.asyncio
async def test_get_connection_from_db_maps_not_found_to_value_error(monkeypatch):
    user = SimpleNamespace(role="user", id="user-1", organization_id="org-1")
    service = FakeConnectionService(exc=ConnectionNotFoundError("conn-1"))
    log_calls = []

    _patch_user(monkeypatch, user)
    monkeypatch.setattr(
        get_exist_db_connection,
        "_build_connection_service",
        lambda: service,
    )
    monkeypatch.setattr(get_exist_db_connection.logger, "error", log_calls.append)

    node = _make_node()

    with pytest.raises(ValueError, match="No DB connection found"):
        await node._get_connection_from_db()

    assert log_calls


@pytest.mark.asyncio
async def test_get_connection_from_db_maps_access_denied_to_value_error(monkeypatch):
    user = SimpleNamespace(role="user", id="user-1", organization_id="org-1")
    service = FakeConnectionService(exc=AccessDeniedError("denied"))
    log_calls = []

    _patch_user(monkeypatch, user)
    monkeypatch.setattr(
        get_exist_db_connection,
        "_build_connection_service",
        lambda: service,
    )
    monkeypatch.setattr(get_exist_db_connection.logger, "error", log_calls.append)

    node = _make_node()

    with pytest.raises(ValueError, match="No DB connection found"):
        await node._get_connection_from_db()

    assert log_calls


@pytest.mark.asyncio
async def test_get_connection_from_db_rejects_non_sql_record(monkeypatch):
    user = SimpleNamespace(role="admin", id="user-1", organization_id="org-1")
    service = FakeConnectionService(
        record=_make_connection_record(kind="file", connection_type="smbprotocol")
    )
    log_calls = []

    _patch_user(monkeypatch, user)
    monkeypatch.setattr(
        get_exist_db_connection,
        "_build_connection_service",
        lambda: service,
    )
    monkeypatch.setattr(get_exist_db_connection.logger, "error", log_calls.append)

    node = _make_node()

    with pytest.raises(TypeError, match="is not a SQL connection"):
        await node._get_connection_from_db()

    assert log_calls[-1] == "Connection with ID conn-1 is not a SQL connection."


@pytest.mark.asyncio
async def test_get_connection_from_db_raises_when_user_missing(monkeypatch):
    log_calls = []

    _patch_user(monkeypatch, None)
    monkeypatch.setattr(get_exist_db_connection.logger, "error", log_calls.append)

    node = _make_node()

    with pytest.raises(ValueError, match="No DB connection found"):
        await node._get_connection_from_db()

    assert log_calls
