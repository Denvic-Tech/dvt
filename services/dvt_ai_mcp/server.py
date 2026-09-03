from __future__ import annotations

import time
from typing import Any, Literal

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR, ToolAnnotations
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .gateway_client import (
    GatewayToolError,
    bearer_token_context,
    gateway_client,
)
from .models import DDLColumn, GraphPatch, RuntimeVariable, TableCreateSpec
from .settings import settings

INSTRUCTIONS = """
You work with DVT visual ETL projects. Before editing, inspect the project graph and search the
available node catalog. Prefer specialized low-code source, transform, and sink nodes over generic
code nodes, and build a readable left-to-right graph with meaningful display names and comments.
Never add or replace a node with a deprecated node type. Deprecated nodes found in an existing
graph may be inspected for compatibility, but must not be selected for new development.
ExecutePython, DataFrameExecCode, and ExecuteSQL are allowed only when justified by a non-empty
comment. Always validate changes before applying them. After applying, run the full project (or the
explicit target nodes), wait until a terminal state, and never claim success before SUCCESS. On
ERROR, read task logs, fix the graph, validate, apply, run, and wait again. Project names are only
for discovery; if a search returns multiple projects, present the candidates instead of guessing,
and use project_id for every mutation and execution. Never attempt to infer or expose
connection credentials. Subgraphs may be inspected and existing membership may be changed, but
subgraph entities must not be created, updated, or deleted.

Every runtime input whose node definition type is DB_CONNECTION, S3_CONNECTION, FTP_CONNECTION,
or SMB_CONNECTION is an object port and must be supplied by a graph edge from the matching
connection node: GetExistDBConnection, GetExistS3Connection, GetExistFTPConnection, or
GetExistSMBConnection. Never put a connection ID string or connection_ref directly into a
consumer's connection object input. Put connection_ref only into the connection node's
connection_id input, then add an edge from that node's connection output to every consumer's
connection input. The same connection node may feed multiple consumers. Before validation, audit
every added or changed source, sink, SQL, and storage node and ensure each required connection
object port has such an incoming edge.

For an ordinary database table read, use ReadTableFromDBV3. Use ReadQueryFromDBV3 only when the
required source-side behavior cannot reasonably be expressed by ReadTableFromDBV3 followed by
specialized low-code filter, projection, join, grouping, aggregation, or transform nodes. When
ReadQueryFromDBV3 is necessary, explain the specific reason in the node comment.

Before configuring ReadTableFromDBV3, inspect the table with get_database_table. Always set
partition_col to an exact raw catalog column name without SQL quotes or backticks. Choose a stable,
non-null scalar column with useful cardinality; prefer a primary key or indexed numeric/datetime
column. Configure partition_grouping only when the catalog shape and expected data distribution
justify it, and prefer specialized low-code aggregation nodes for business aggregations.
Always set columns to an explicit non-empty list.
When no projection is requested, pass every catalog column so the UI and runtime both represent
"all columns". In update_nodes.inputs, omit keys that must stay unchanged. A null input entry
removes the persisted value and must not be used as "all columns".

WriteDataFrameToDBV4 never creates a target database, schema, or table. Before using it, inspect
the target catalog and verify that the exact target table exists. If a database, schema, or table
is missing, create it first with create_database, create_schema, or create_table using the intended
DataFrame metadata and target constraints, then inspect the created table again before applying or
running the graph. Never rely on the write node to infer or create the target structure.
""".strip()

TOOL_CALLS = Counter(
    "dvt_ai_mcp_tool_calls_total",
    "DVT AI MCP tool calls by outcome.",
    ("tool", "outcome"),
)
TOOL_DURATION = Histogram(
    "dvt_ai_mcp_tool_duration_seconds",
    "DVT AI MCP tool call duration.",
    ("tool",),
)
AUTH_FAILURES = Counter(
    "dvt_ai_mcp_auth_failures_total",
    "DVT AI MCP transport authentication failures.",
    ("code",),
)
SCOPE_FAILURES = Counter(
    "dvt_ai_mcp_scope_failures_total",
    "DVT AI MCP scope and resource-access failures.",
    ("code",),
)
VALIDATION_FAILURES = Counter(
    "dvt_ai_mcp_validation_failures_total",
    "DVT AI MCP graph validation failures.",
)
MCP_TASK_RUNS = Counter(
    "dvt_ai_mcp_task_runs_total",
    "Projects queued through DVT AI MCP.",
)
MCP_TASK_TERMINAL = Counter(
    "dvt_ai_mcp_task_terminal_total",
    "Terminal outcomes observed through DVT AI MCP.",
    ("status",),
)
SQL_TIMEOUTS = Counter(
    "dvt_ai_mcp_sql_timeouts_total",
    "Read-only SQL requests that timed out.",
)
GATEWAY_FAILURES = Counter(
    "dvt_ai_mcp_gateway_failures_total",
    "Gateway calls unavailable to DVT AI MCP.",
)

mcp = MCPServer("dvt_ai_mcp", instructions=INSTRUCTIONS)


async def _call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    outcome = "success"
    try:
        result = await gateway_client.call_tool(
            tool_name,
            {key: value for key, value in arguments.items() if value is not None},
        )
    except GatewayToolError as exc:
        outcome = exc.code
        if exc.code in {
            "SCOPE_DENIED",
            "PROJECT_NOT_FOUND_OR_DENIED",
            "CONNECTION_NOT_FOUND_OR_DENIED",
            "TASK_NOT_FOUND_OR_DENIED",
        }:
            SCOPE_FAILURES.labels(code=exc.code).inc()
        elif exc.code == "GRAPH_VALIDATION_FAILED":
            VALIDATION_FAILURES.inc()
        elif exc.code == "QUERY_TIMEOUT":
            SQL_TIMEOUTS.inc()
        elif exc.code == "GATEWAY_UNAVAILABLE":
            GATEWAY_FAILURES.inc()
        raise MCPError(
            code=INTERNAL_ERROR,
            message=exc.message,
            data={"dvt_error": exc.to_mapping()},
        ) from exc
    else:
        if tool_name == "run_project":
            MCP_TASK_RUNS.inc()
        if tool_name in {"get_task", "wait_task"} and result.get("terminal"):
            MCP_TASK_TERMINAL.labels(status=str(result.get("status", "UNKNOWN"))).inc()
        return result
    finally:
        TOOL_CALLS.labels(tool=tool_name, outcome=outcome).inc()
        TOOL_DURATION.labels(tool=tool_name).observe(time.monotonic() - started)


READ_CLOSED = ToolAnnotations(read_only_hint=True, open_world_hint=False)
READ_OPEN = ToolAnnotations(read_only_hint=True, open_world_hint=True)
WRITE_GRAPH = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,
)
WRITE_EXECUTION = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)
WRITE_DDL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)
CANCEL_EXECUTION = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=True,
)


@mcp.tool(annotations=READ_CLOSED)
async def list_projects(
    search: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List projects accessible through this MCP token; names may be ambiguous."""
    return await _call("list_projects", locals())


@mcp.tool(annotations=READ_CLOSED)
async def get_project(project_id: str) -> dict[str, Any]:
    """Get project metadata and typed project variables by immutable project ID."""
    return await _call("get_project", locals())


@mcp.tool(annotations=READ_CLOSED)
async def get_project_graph(
    project_id: str,
    cursor: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Read a stable graph page with graph_revision and graph_etag concurrency tokens."""
    return await _call("get_project_graph", locals())


@mcp.tool(annotations=READ_CLOSED)
async def search_nodes(
    query: str = "",
    category: str | None = None,
    tags: list[str] | None = None,
    input_type: str | None = None,
    output_type: str | None = None,
    limit: int = 50,
    locale: str = "en",
) -> dict[str, Any]:
    """Lexically search ready core and extension low-code nodes and their type capabilities."""
    return await _call("search_nodes", locals())


@mcp.tool(annotations=READ_CLOSED)
async def get_node_definition(node_name: str, locale: str = "en") -> dict[str, Any]:
    """Get the complete schema and documentation for one available node type."""
    return await _call("get_node_definition", locals())


@mcp.tool(annotations=READ_CLOSED)
async def validate_graph_changes(
    project_id: str,
    expected_graph_revision: int,
    expected_graph_etag: str,
    patch: GraphPatch,
) -> dict[str, Any]:
    """Validate an atomic graph patch without persisting it and return quality warnings."""
    return await _call("validate_graph_changes", locals())


@mcp.tool(annotations=WRITE_GRAPH)
async def apply_graph_changes(
    project_id: str,
    expected_graph_revision: int,
    expected_graph_etag: str,
    patch: GraphPatch,
) -> dict[str, Any]:
    """Atomically apply a validated graph patch if both concurrency tokens still match."""
    return await _call("apply_graph_changes", locals())


@mcp.tool(annotations=READ_CLOSED)
async def list_connections(
    kind: str | None = None,
    search: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List accessible SQL and file connections without credentials; queues are excluded."""
    return await _call("list_connections", locals())


@mcp.tool(annotations=READ_CLOSED)
async def get_connection(connection_id: str) -> dict[str, Any]:
    """Get masked metadata and capabilities for an accessible connection."""
    return await _call("get_connection", locals())


@mcp.tool(annotations=READ_OPEN)
async def browse_database(
    connection_id: str,
    level: Literal["databases", "schemas", "tables"],
    parent_filters: dict[str, str | None] | None = None,
    search: str | None = None,
    cursor: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Browse database, schema, or table catalog pages through an accessible SQL connection."""
    parents = parent_filters or {}
    return await _call(
        "browse_database",
        {
            "connection_id": connection_id,
            "level": level,
            "database_name": parents.get("database"),
            "schema_name": parents.get("schema"),
            "search": search,
            "cursor": cursor,
            "limit": limit,
        },
    )


@mcp.tool(annotations=READ_OPEN)
async def get_database_table(
    connection_id: str,
    table: str,
    database: str | None = None,
    schema: str | None = None,
) -> dict[str, Any]:
    """Get columns, keys, and indexes for one table from DB Catalog."""
    return await _call(
        "get_database_table",
        {
            "connection_id": connection_id,
            "table_name": table,
            "database_name": database,
            "schema_name": schema,
        },
    )


@mcp.tool(annotations=READ_OPEN)
async def query_database_readonly(
    connection_id: str,
    sql: str,
    parameters: dict[str, Any] | None = None,
    max_rows: int = 100,
) -> dict[str, Any]:
    """Run one AST-validated SELECT/WITH/safe EXPLAIN in a read-only source session."""
    return await _call("query_database_readonly", locals())


@mcp.tool(annotations=WRITE_DDL)
async def create_database(connection_id: str, database_name: str) -> dict[str, Any]:
    """Create a missing database through a scoped SQL connection; existing targets are unchanged."""
    return await _call("create_database", locals())


@mcp.tool(annotations=WRITE_DDL)
async def create_schema(
    connection_id: str,
    schema_name: str,
    database_name: str | None = None,
) -> dict[str, Any]:
    """Create a missing schema through a scoped SQL connection; existing targets are unchanged."""
    return await _call("create_schema", locals())


@mcp.tool(annotations=WRITE_DDL)
async def create_table(
    connection_id: str,
    table_name: str,
    columns: list[DDLColumn],
    database_name: str | None = None,
    schema_name: str | None = None,
    table_create_spec: TableCreateSpec | None = None,
) -> dict[str, Any]:
    """Create a missing typed table for WriteDataFrameToDBV4; existing targets are unchanged."""
    return await _call("create_table", locals())


@mcp.tool(annotations=READ_OPEN)
async def list_storage(
    connection_id: str,
    path: str = "",
    cursor: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List a safe relative path in S3, SMB, FTP, SFTP, or DVT service storage."""
    return await _call("list_storage", locals())


@mcp.tool(annotations=READ_OPEN)
async def preview_storage_file(
    connection_id: str,
    path: str,
    max_rows: int = 100,
    max_bytes: int = 262144,
) -> dict[str, Any]:
    """Return a bounded text/tabular preview without binary bytes or presigned URLs."""
    return await _call("preview_storage_file", locals())


@mcp.tool(annotations=WRITE_EXECUTION)
async def run_project(
    project_id: str,
    target_node_ids: list[str] | None = None,
    runtime_variables: dict[str, RuntimeVariable] | None = None,
    force_exec: bool = False,
) -> dict[str, Any]:
    """Queue a full or target-node project run after checking all connection dependencies."""
    return await _call("run_project", locals())


@mcp.tool(annotations=READ_CLOSED)
async def get_task(project_id: str, task_id: str) -> dict[str, Any]:
    """Get the current lifecycle state of an accessible project task."""
    return await _call("get_task", locals())


@mcp.tool(annotations=READ_CLOSED)
async def wait_task(
    project_id: str,
    task_id: str,
    timeout_sec: float = 20,
) -> dict[str, Any]:
    """Wait at most 50 seconds for a task transition, returning current or terminal state."""
    return await _call("wait_task", locals())


@mcp.tool(annotations=READ_CLOSED)
async def get_task_logs(
    project_id: str,
    task_id: str,
    cursor: str | None = None,
    limit: int = 100,
    level: str | None = None,
) -> dict[str, Any]:
    """Read stable, paginated, secret-redacted task logs without exception tracebacks."""
    return await _call("get_task_logs", locals())


@mcp.tool(annotations=CANCEL_EXECUTION)
async def cancel_task(project_id: str, task_id: str) -> dict[str, Any]:
    """Request cooperative cancellation of a non-terminal task; no hard stop is issued."""
    return await _call("cancel_task", locals())


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> Response:
    return JSONResponse({"status": "ok", "service": "dvt_ai_mcp"})


@mcp.custom_route("/metrics", methods=["GET"])
async def metrics(_: Request) -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class BearerAuthenticationMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("path") in {"/health", "/metrics"}:
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            AUTH_FAILURES.labels(code="AUTH_INVALID").inc()
            await JSONResponse(
                {
                    "error": {
                        "code": "AUTH_INVALID",
                        "message": "A valid MCP bearer token is required.",
                    }
                },
                status_code=401,
            )(scope, receive, send)
            return
        try:
            await gateway_client.verify(token)
        except GatewayToolError as exc:
            AUTH_FAILURES.labels(code=exc.code).inc()
            status_code = 503 if exc.code == "GATEWAY_UNAVAILABLE" else 401
            await JSONResponse({"error": exc.to_mapping()}, status_code=status_code)(
                scope, receive, send
            )
            return
        context_token = bearer_token_context.set(token)
        try:
            await self.app(scope, receive, send)
        finally:
            bearer_token_context.reset(context_token)


allowed_hosts, allowed_origins = settings.transport_allowlists()
security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=allowed_hosts,
    allowed_origins=allowed_origins,
)
streamable_http_app = mcp.streamable_http_app(
    stateless_http=True,
    json_response=True,
    transport_security=security,
    host=settings.host,
)
app = BearerAuthenticationMiddleware(streamable_http_app)
