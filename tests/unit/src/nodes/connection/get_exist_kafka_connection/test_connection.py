from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.node_dsl import IO
from src.nodes.connection.get_exist_kafka_connection import node as module


@pytest.mark.asyncio
@pytest.mark.parametrize("connection_id", ["catalog-id", 17])
async def test_resolves_record_without_producer(monkeypatch, connection_id):
    record = SimpleNamespace(id=str(connection_id), name="test", kind="queue", type="kafka")
    service = SimpleNamespace(get=AsyncMock(return_value=record))
    monkeypatch.setattr(module, "build_connection_service", lambda **kwargs: service)
    instance = object.__new__(module.GetExistKafkaConnection)
    instance.connection_id = connection_id
    user = object()
    monkeypatch.setattr(module.GetExistKafkaConnection, "_get_user", AsyncMock(return_value=user))
    result = await instance._get_connection_from_db()
    assert result.record is record
    service.get.assert_awaited_once_with(str(connection_id), actor=user)
    assert not module.GetExistKafkaConnection.input_fields()["connection_id"].is_hidden
    assert (
        module.GetExistKafkaConnection.input_fields()["connection_id"].resolved_type
        == IO.KAFKA_CONNECTION_ID
    )
