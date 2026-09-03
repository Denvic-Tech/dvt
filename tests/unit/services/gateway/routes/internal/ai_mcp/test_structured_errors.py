import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.gateway.routes.internal.ai_mcp.errors import AIMCPHTTPError
from services.gateway.routes.internal.ai_mcp.router import call_tool
from services.gateway.routes.internal.ai_mcp.schemas import ToolCallSchema

from src.exception_registry.handlers import exception_handler


class _RollbackExpiringIdentity:
    def __init__(self, identity: str) -> None:
        self._identity = identity
        self.expired = False

    @property
    def id(self) -> str:
        if self.expired:
            raise RuntimeError("ORM identity was accessed after rollback")
        return self._identity


@pytest.mark.asyncio
async def test_gateway_exception_handler_preserves_ai_mcp_error_contract() -> None:
    response = await exception_handler(
        None,
        AIMCPHTTPError(
            403,
            "SCOPE_DENIED",
            "Resource is unavailable.",
            details={"resource": "project"},
        ),
    )

    assert response.status_code == 403
    assert json.loads(response.body) == {
        "detail": {
            "code": "SCOPE_DENIED",
            "message": "Resource is unavailable.",
            "details": {"resource": "project"},
        }
    }


@pytest.mark.asyncio
async def test_invalid_graph_patch_uses_structured_validation_error() -> None:
    session = AsyncMock()
    user = _RollbackExpiringIdentity("user-id")
    session.rollback.side_effect = lambda: setattr(user, "expired", True)
    principal = SimpleNamespace(
        user=user,
        token=SimpleNamespace(id="token-id"),
    )
    payload = ToolCallSchema(
        arguments={
            "project_id": "project-id",
            "expected_graph_revision": 1,
            "expected_graph_etag": "etag",
            "patch": {"add_nodes": [{"id": "", "node_type": "ExecutePython"}]},
        }
    )

    with pytest.raises(AIMCPHTTPError) as raised:
        await call_tool(
            "validate_graph_changes",
            payload,
            session,
            principal,
            None,
            None,
        )

    assert raised.value.detail["code"] == "GRAPH_VALIDATION_FAILED"
    session.rollback.assert_awaited_once()
