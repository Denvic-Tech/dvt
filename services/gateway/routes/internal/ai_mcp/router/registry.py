"""Tool registration: handler, injected dependencies and existing call policies."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from .. import context, data, ddl, ddl_columns, graph, projects, schedules, tasks
from ..errors import AIMCPHTTPError

ToolHandler = Callable[..., Awaitable[dict[str, Any]]]
Dependency = Literal["session", "redis", "orchestrator"]
CommitPolicy = Literal["never", "always", "unless_dry_run"]
ValidationErrorCode = Literal["INVALID_ARGUMENTS", "GRAPH_VALIDATION_FAILED"]


@dataclass(frozen=True)
class Tool:
    handler: ToolHandler
    dependencies: tuple[Dependency, ...] = ()
    reject_reserved_arguments: bool = False
    check_signature: bool = False
    validation_error_code: ValidationErrorCode = "GRAPH_VALIDATION_FAILED"
    commit: CommitPolicy = "never"

    def should_commit(self, arguments: dict[str, Any]) -> bool:
        return self.commit == "always" or (
            self.commit == "unless_dry_run" and not arguments.get("dry_run", True)
        )


# Policies intentionally preserve existing differences between tool contracts.
# Tools whose use cases own their transaction do not request a router commit.
TOOLS: dict[str, Tool] = {
    "list_projects": Tool(context.list_projects, ("session",)),
    "get_project": Tool(context.get_project, ("session",)),
    "search_nodes": Tool(context.search_nodes, ("session",)),
    "get_node_definition": Tool(context.get_node_definition, ("session",)),
    "create_project": Tool(
        projects.create_project,
        ("session",),
        reject_reserved_arguments=True,
        check_signature=True,
        validation_error_code="INVALID_ARGUMENTS",
    ),
    "list_project_schedules": Tool(
        schedules.list_project_schedules,
        ("session",),
        reject_reserved_arguments=True,
        check_signature=True,
        validation_error_code="INVALID_ARGUMENTS",
    ),
    "get_project_schedule": Tool(
        schedules.get_project_schedule,
        ("session",),
        reject_reserved_arguments=True,
        check_signature=True,
        validation_error_code="INVALID_ARGUMENTS",
    ),
    "set_project_schedule": Tool(
        schedules.set_project_schedule,
        ("session",),
        reject_reserved_arguments=True,
        check_signature=True,
        validation_error_code="INVALID_ARGUMENTS",
    ),
    "update_project_schedule": Tool(
        schedules.update_project_schedule,
        ("session",),
        reject_reserved_arguments=True,
        check_signature=True,
        validation_error_code="INVALID_ARGUMENTS",
    ),
    "set_project_schedule_enabled": Tool(
        schedules.set_project_schedule_enabled,
        ("session",),
        reject_reserved_arguments=True,
        check_signature=True,
        validation_error_code="INVALID_ARGUMENTS",
    ),
    "get_project_graph": Tool(
        graph.get_project_graph,
        ("session",),
        reject_reserved_arguments=True,
        check_signature=True,
    ),
    "validate_graph_changes": Tool(
        graph.validate_graph_changes,
        ("session",),
        reject_reserved_arguments=True,
        check_signature=True,
    ),
    "apply_graph_changes": Tool(
        graph.apply_graph_changes,
        ("session",),
        reject_reserved_arguments=True,
        check_signature=True,
        commit="always",
    ),
    "auto_layout_project": Tool(
        graph.auto_layout_project,
        ("session",),
        reject_reserved_arguments=True,
        check_signature=True,
        commit="unless_dry_run",
    ),
    "list_connections": Tool(data.list_connections, ("session",)),
    "get_connection": Tool(data.get_connection, ("session",)),
    "browse_database": Tool(data.browse_database, ("redis",)),
    "get_database_table": Tool(data.get_database_table, ("redis",)),
    "query_database_readonly": Tool(data.query_database_readonly),
    "list_storage": Tool(data.list_storage, ("session",)),
    "preview_storage_file": Tool(data.preview_storage_file, ("session",)),
    "create_database": Tool(ddl.create_database, ("redis",)),
    "create_schema": Tool(ddl.create_schema, ("redis",)),
    "create_table": Tool(ddl.create_table, ("redis",)),
    "resolve_write_columns": Tool(
        ddl_columns.resolve_write_columns, reject_reserved_arguments=True
    ),
    "apply_table_column_actions": Tool(
        ddl_columns.apply_table_column_actions,
        ("redis",),
        reject_reserved_arguments=True,
    ),
    "run_project": Tool(tasks.run_project, ("session",), commit="always"),
    "get_task": Tool(tasks.get_task, ("session",)),
    "wait_task": Tool(tasks.wait_task, ("session",)),
    "get_task_logs": Tool(tasks.get_task_logs, ("session",)),
    "cancel_task": Tool(tasks.cancel_task, ("session", "orchestrator"), commit="always"),
}


def get_tool(name: str) -> Tool:
    tool = TOOLS.get(name)
    if tool is None:
        raise AIMCPHTTPError(404, "NODE_NOT_AVAILABLE", "MCP tool is not available.")
    return tool
