"""Prepare call arguments without mutating the incoming request."""

import inspect
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.orchestrator_client import GrpcOrchestratorClient

from ..auth import MCPPrincipal
from ..errors import AIMCPHTTPError
from ..graph.schemas import GraphPatchSchema
from .registry import Tool

_RESERVED_ARGUMENTS = frozenset({"principal", "session", "redis"})


def prepare_arguments(
    name: str,
    tool: Tool,
    arguments: dict[str, Any],
    *,
    principal: MCPPrincipal,
    session: AsyncSession,
    redis: Redis,
    orchestrator: GrpcOrchestratorClient,
) -> dict[str, Any]:
    if tool.reject_reserved_arguments and _RESERVED_ARGUMENTS.intersection(arguments):
        raise AIMCPHTTPError(422, "INVALID_ARGUMENTS", "Reserved tool arguments.")

    kwargs = {**arguments, "principal": principal}
    if name in {"validate_graph_changes", "apply_graph_changes"}:
        kwargs["patch"] = GraphPatchSchema.model_validate(kwargs.get("patch", {}))

    dependencies = {"session": session, "redis": redis, "orchestrator": orchestrator}
    for dependency in tool.dependencies:
        kwargs[dependency] = dependencies[dependency]

    if tool.check_signature:
        _check_signature(tool, kwargs)
    if name == "auto_layout_project" and not isinstance(kwargs.get("dry_run", True), bool):
        raise AIMCPHTTPError(422, "INVALID_ARGUMENTS", "dry_run must be a boolean.")
    return kwargs


def _check_signature(tool: Tool, arguments: dict[str, Any]) -> None:
    try:
        inspect.signature(tool.handler).bind(**arguments)
    except TypeError as exc:
        raise AIMCPHTTPError(422, "INVALID_ARGUMENTS", "Tool arguments are invalid.") from exc
