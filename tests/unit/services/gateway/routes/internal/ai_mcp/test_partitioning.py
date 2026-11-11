from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.gateway.routes.impl.partitioning_advice import PartitioningAdviceError
from services.gateway.routes.internal.ai_mcp import partitioning
from services.gateway.routes.internal.ai_mcp.errors import AIMCPHTTPError
from services.gateway.routes.internal.ai_mcp.router.registry import TOOLS


@pytest.fixture
def context(monkeypatch):
    principal = SimpleNamespace(user=object())
    access = AsyncMock(return_value=SimpleNamespace(kind="sql"))
    resolve = AsyncMock(
        return_value=SimpleNamespace(
            connection_id="allowed", connection_string="postgresql://user:secret@host/db"
        )
    )
    monkeypatch.setattr(partitioning, "get_accessible_connection", access)
    monkeypatch.setattr(partitioning, "resolve_ddl_connection", resolve)
    return principal, access, resolve


async def test_forwards_a_validated_request_without_the_connection_id(context, monkeypatch):
    principal, access, _ = context
    advice = AsyncMock(
        return_value=SimpleNamespace(model_dump=lambda mode: {"recommendations": [], "mode": mode})
    )
    monkeypatch.setattr(partitioning, "_suggest_read_partitioning", advice)

    result = await partitioning.suggest_read_partitioning(
        principal=principal, connection_id="allowed", table_name="sales", columns=["id"]
    )

    assert result == {"recommendations": [], "mode": "json"}
    access.assert_awaited_once_with(principal, "allowed")
    connection_string, request = advice.await_args.args
    assert connection_string == "postgresql://user:secret@host/db"
    assert request.table_name == "sales"
    assert request.columns == ["id"]
    assert request.model_fields_set == {"table_name", "columns"}


@pytest.mark.parametrize(
    "arguments",
    [
        {"connection_id": "allowed"},
        {"connection_id": "allowed", "table_name": "t", "sql_code": "SELECT 1"},
        {"table_name": "t"},
        {"connection_id": "allowed", "table_name": "t", "unknown": 1},
    ],
)
async def test_invalid_arguments(context, arguments):
    principal, _, resolve = context
    with pytest.raises(AIMCPHTTPError) as raised:
        await partitioning.suggest_read_partitioning(principal=principal, **arguments)
    assert raised.value.detail["code"] == "INVALID_ARGUMENTS"
    resolve.assert_not_awaited()


async def test_non_sql_connection_is_denied(context):
    principal, access, resolve = context
    access.return_value = SimpleNamespace(kind="storage")
    with pytest.raises(AIMCPHTTPError) as raised:
        await partitioning.suggest_read_partitioning(
            principal=principal, connection_id="allowed", table_name="t"
        )
    assert (raised.value.status_code, raised.value.detail["code"]) == (
        404,
        "CONNECTION_NOT_FOUND_OR_DENIED",
    )
    resolve.assert_not_awaited()


async def test_advice_errors_keep_status_and_code(context, monkeypatch):
    principal, _, _ = context
    advice = AsyncMock(side_effect=PartitioningAdviceError(504, "ADVICE_TIMEOUT", "slow"))
    monkeypatch.setattr(partitioning, "_suggest_read_partitioning", advice)
    with pytest.raises(AIMCPHTTPError) as raised:
        await partitioning.suggest_read_partitioning(
            principal=principal, connection_id="allowed", sql_code="SELECT 1"
        )
    assert raised.value.status_code == 504
    assert raised.value.detail == {"code": "ADVICE_TIMEOUT", "message": "slow"}


def test_tool_is_registered_without_extra_dependencies():
    tool = TOOLS["suggest_read_partitioning"]
    assert tool.handler is partitioning.suggest_read_partitioning
    assert tool.dependencies == ()
    assert tool.reject_reserved_arguments is True
    assert tool.should_commit({}) is False
