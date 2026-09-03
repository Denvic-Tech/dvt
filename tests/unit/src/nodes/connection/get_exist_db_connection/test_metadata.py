import json
from datetime import UTC, datetime

import pytest
from db_connection.domain import ConnectionRecord

from src.node_dsl import SqlConnectionRecord
from src.nodes.connection.get_exist_db_connection import GetExistDBConnection


def _make_node():
    return GetExistDBConnection(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-1",
        connection_id="conn-1",
    )


def _record() -> SqlConnectionRecord:
    now = datetime.now(UTC)
    return SqlConnectionRecord(ConnectionRecord(
        id="conn-1",
        name="SQLite",
        kind="sql",
        type="sqlite",
        driver="pysqlite",
        driver_options=None,
        properties={"database": "catalog.sqlite"},
        secrets={},
        labels={},
        metadata={},
        extra={},
        created_at=now,
        updated_at=now,
    ))


@pytest.mark.asyncio
async def test_metadata_returns_small_lazy_descriptor_without_customer_db_access(monkeypatch):
    node = _make_node()
    node.connection = _record()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("customer DB access is forbidden for GetExistDBConnection metadata")

    monkeypatch.setattr("sqlalchemy.create_engine", forbidden)

    metadata = (await node.resolve_metadata())["connection"]

    assert metadata.type.value == "DATABASE"
    assert metadata.connection_id == "conn-1"
    assert metadata.connection_revision is not None
    assert metadata.catalog_mode == "lazy"
    assert metadata.catalog_capabilities.supports_schemas is True
    assert metadata.database_name == "catalog.sqlite"
    assert metadata.connection_string is None
    assert metadata.databases == []
    assert metadata.schemas == []
    assert metadata.tables == []
    assert len(json.dumps(metadata.model_dump(mode="json")).encode()) < 2048


def test_get_metadata_cache_key_uses_base_behavior():
    assert _make_node().get_metadata_cache_key() is None
