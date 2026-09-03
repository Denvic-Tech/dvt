from typing import ClassVar

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from services.gateway.update_runtime.monitor import SystemStateMonitor

from src.schemas.http.system import SystemStateValue


class SystemUpdateMiddleware:
    _ALLOWED_EXACT_PATHS: ClassVar[set[str]] = {"/health", "/system/state"}
    _ALLOWED_PREFIXES: ClassVar[tuple[str, ...]] = ("/auth", "/metrics", "/update")

    def __init__(self, app: ASGIApp, monitor: SystemStateMonitor):
        self.app = app
        self._monitor = monitor

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        path = self._normalized_path(scope)
        if self._is_allowed(scope, path):
            await self.app(scope, receive, send)
            return

        snapshot = self._monitor.snapshot
        if snapshot.state != SystemStateValue.UPDATING:
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send(
                {
                    "type": "websocket.close",
                    "code": 1013,
                    "reason": "DVT is being updated",
                }
            )
            return

        response = JSONResponse(
            status_code=503,
            headers={"Retry-After": str(snapshot.retry_after_sec)},
            content={
                "name": "SYSTEM_UPDATING",
                "code": "SYSTEM_UPDATING",
                "description": "DVT is being updated",
                "category": "GATEWAY_INTERNAL",
                "type": "HTTP_GENERATED",
                "exc_data": {"retry_after": snapshot.retry_after_sec},
            },
        )
        await response(scope, receive, send)

    @classmethod
    def _is_allowed(cls, scope: Scope, path: str) -> bool:
        if scope["type"] == "http" and scope.get("method") == "OPTIONS":
            return True
        if path in cls._ALLOWED_EXACT_PATHS:
            return True
        return any(
            path == prefix or path.startswith(f"{prefix}/") for prefix in cls._ALLOWED_PREFIXES
        )

    @staticmethod
    def _normalized_path(scope: Scope) -> str:
        path = scope.get("path", "") or "/"
        root_path = (scope.get("root_path", "") or "").rstrip("/")
        if root_path and path.startswith(f"{root_path}/"):
            path = path[len(root_path) :]
        return path or "/"
