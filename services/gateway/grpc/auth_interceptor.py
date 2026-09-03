import grpc
from typing import Optional, Iterable

from src.logger import logger


class AuthInterceptor(grpc.aio.ServerInterceptor):
    """
    Простая авторизация для grpc.aio-сервера:
      - если expected_token пуст → пропускаем всех (dev-режим)
      - принимаем либо "authorization: Bearer <token>", либо "x-api-key: <token>"
      - allowlist по именам методов (полные пути вида "/pkg.svc/Method")
      - при неуспехе подменяем handler так, чтобы он всегда делал ctx.abort(UNAUTHENTICATED)
    """

    def __init__(self, expected_token: Optional[str], allowlist: Iterable[str] = ()):
        self.expected_token = expected_token
        self.allowlist = tuple(allowlist)

    @staticmethod
    def _extract_token(md_items: Optional[Iterable[tuple[str, str]]]) -> Optional[str]:
        md = dict(md_items or [])
        auth = md.get("authorization")
        if auth:
            low = auth.lower()
            if low.startswith("bearer "):
                return auth[7:].strip()

            return auth.strip()

        api_key = md.get("x-api-key")
        if api_key:
            return api_key.strip()

        return None

    async def intercept_service(self, continuation, hcd: grpc.HandlerCallDetails) -> grpc.RpcMethodHandler:
        handler = await continuation(hcd)
        if hcd.method in self.allowlist:
            return handler

        if not self.expected_token:
            return handler

        incoming_token = self._extract_token(hcd.invocation_metadata)
        if incoming_token == self.expected_token:
            return handler

        async def deny(request_or_iterator, context: grpc.aio.ServicerContext):
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid token")

        replace_kwargs = {}
        if getattr(handler, "unary_unary", None) is not None:
            replace_kwargs["unary_unary"] = deny
        if getattr(handler, "unary_stream", None) is not None:
            replace_kwargs["unary_stream"] = deny
        if getattr(handler, "stream_unary", None) is not None:
            replace_kwargs["stream_unary"] = deny
        if getattr(handler, "stream_stream", None) is not None:
            replace_kwargs["stream_stream"] = deny

        if not replace_kwargs:
            return handler

        return handler._replace(**replace_kwargs)
