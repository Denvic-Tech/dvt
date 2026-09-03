import contextvars
import json
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel

from .settings import settings

bearer_token_context: contextvars.ContextVar[str] = contextvars.ContextVar("dvt_mcp_token")

KNOWN_ERROR_CODES = frozenset(
    {
        "AUTH_INVALID",
        "TOKEN_EXPIRED",
        "TOKEN_REVOKED",
        "INTERNAL_AUTH_FAILED",
        "SCOPE_DENIED",
        "PROJECT_NOT_FOUND_OR_DENIED",
        "CONNECTION_NOT_FOUND_OR_DENIED",
        "GRAPH_REVISION_CONFLICT",
        "GRAPH_ETAG_CONFLICT",
        "GRAPH_VALIDATION_FAILED",
        "NODE_NOT_AVAILABLE",
        "UNSAFE_SQL",
        "QUERY_TIMEOUT",
        "RESULT_TOO_LARGE",
        "DDL_OPERATION_FAILED",
        "DDL_UNSUPPORTED",
        "STORAGE_PREVIEW_UNSUPPORTED",
        "TASK_NOT_FOUND_OR_DENIED",
        "GATEWAY_UNAVAILABLE",
    }
)


class GatewayToolError(RuntimeError):
    def __init__(self, code: str, message: str, details: Any | None = None) -> None:
        self.code = code
        self.message = message
        self.details = details
        super().__init__(json.dumps(self.to_mapping(), ensure_ascii=False))

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            payload["details"] = self.details
        return payload


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_unset=True)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


class GatewayClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.gateway_url,
            timeout=httpx.Timeout(58.0, connect=5.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    @staticmethod
    def _headers(token: str, correlation_id: str | None = None) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "X-DVT-AI-MCP-Internal-Secret": settings.internal_secret,
            "X-Correlation-ID": correlation_id or str(uuid4()),
        }

    async def _request(self, path: str, *, token: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(path, headers=self._headers(token), json=body)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise GatewayToolError("GATEWAY_UNAVAILABLE", "Gateway is unavailable.") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise GatewayToolError(
                "GATEWAY_UNAVAILABLE", "Gateway returned an invalid response."
            ) from exc
        if response.is_error:
            detail = payload.get("detail", payload) if isinstance(payload, dict) else {}
            code = str(detail.get("code", "GATEWAY_UNAVAILABLE"))
            if code not in KNOWN_ERROR_CODES:
                raise GatewayToolError("GATEWAY_UNAVAILABLE", "Gateway operation failed.")
            raise GatewayToolError(
                code,
                str(detail.get("message", "Gateway operation failed.")),
                detail.get("details"),
            )
        return payload

    async def verify(self, token: str) -> dict[str, Any]:
        return await self._request("/internal/ai-mcp/v1/auth/verify", token=token, body={})

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        token = bearer_token_context.get(None)
        if not token:
            raise GatewayToolError("AUTH_INVALID", "A valid MCP bearer token is required.")
        payload = await self._request(
            f"/internal/ai-mcp/v1/tools/{tool_name}",
            token=token,
            body={"arguments": _jsonable(arguments)},
        )
        return payload["result"]


gateway_client = GatewayClient()
