import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.gateway.routes.internal.ai_mcp import context, router
from services.gateway.routes.internal.ai_mcp.errors import AIMCPHTTPError
from services.gateway.routes.internal.ai_mcp.schemas import ToolCallSchema


class _Definition:
    name = "FilterDataFrame"
    display_name = "Filter DataFrame"
    description = "Filter rows in a DataFrame."
    category = "transform"
    type = "transform"
    extension_name = None

    def __init__(self) -> None:
        self.tags = ["filter"]
        self.input_definitions = {"dataframe": SimpleNamespace(type="DATAFRAME")}
        self.output_definitions = {"dataframe": SimpleNamespace(type="DATAFRAME")}

    def model_dump(self, *, mode: str) -> dict:
        assert mode == "json"
        return {"name": self.name, "display_name": self.display_name}


def _principal():
    return SimpleNamespace(
        user=SimpleNamespace(id="user-id"),
        token=SimpleNamespace(id="token-id"),
    )


@pytest.mark.asyncio
async def test_node_catalog_tools_accept_dispatcher_dependencies_concurrently(monkeypatch) -> None:
    definition = _Definition()
    monkeypatch.setattr(
        context,
        "_available_definitions",
        AsyncMock(return_value={definition.name: definition}),
    )
    monkeypatch.setattr(context, "get_definition", lambda **_kwargs: definition)
    monkeypatch.setattr(
        context,
        "_node_documentation",
        AsyncMock(return_value="Node documentation."),
    )

    search_result, definition_result = await asyncio.gather(
        router.call_tool(
            "search_nodes",
            ToolCallSchema(arguments={"query": "filter"}),
            AsyncMock(),
            _principal(),
            None,
            None,
        ),
        router.call_tool(
            "get_node_definition",
            ToolCallSchema(arguments={"node_name": definition.name}),
            AsyncMock(),
            _principal(),
            None,
            None,
        ),
    )

    assert search_result.result["items"][0]["name"] == definition.name
    assert definition_result.result == {
        "name": definition.name,
        "display_name": definition.display_name,
        "documentation": "Node documentation.",
    }


@pytest.mark.asyncio
async def test_handler_contract_type_error_is_internal_gateway_failure(monkeypatch) -> None:
    async def incompatible_handler(*, session, principal):
        raise TypeError("internal handler contract mismatch")

    monkeypatch.setitem(router._CONTEXT_HANDLERS, "search_nodes", incompatible_handler)
    session = AsyncMock()

    with pytest.raises(AIMCPHTTPError) as raised:
        await router.call_tool(
            "search_nodes",
            ToolCallSchema(arguments={}),
            session,
            _principal(),
            None,
            None,
        )

    assert raised.value.status_code == 500
    assert raised.value.detail == {
        "code": "GATEWAY_UNAVAILABLE",
        "message": "Gateway operation failed.",
    }
    session.rollback.assert_awaited_once()
