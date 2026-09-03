from typing import Any

from fastapi import HTTPException

from src.exception_registry import RegisteredHTTPException


class AIMCPHTTPError(RegisteredHTTPException):
    name = "AI_MCP_ERROR"
    code = "AI_MCP_ERROR"
    description = "AI MCP request failed."

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: Any | None = None,
    ) -> None:
        detail: dict[str, Any] = {"code": code, "message": message}
        if details is not None:
            detail["details"] = details
        HTTPException.__init__(self, status_code=status_code, detail=detail)

    def serialize(self) -> dict[str, Any]:
        return {"detail": self.detail}


def denied(resource: str) -> AIMCPHTTPError:
    code = {
        "project": "PROJECT_NOT_FOUND_OR_DENIED",
        "connection": "CONNECTION_NOT_FOUND_OR_DENIED",
        "task": "TASK_NOT_FOUND_OR_DENIED",
    }[resource]
    return AIMCPHTTPError(404, code, f"{resource.capitalize()} was not found or is not accessible.")
