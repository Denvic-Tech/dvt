# DVT AI MCP

`dvt_ai_mcp` is the stateless MCP adapter for end users and their coding agents. It exposes
Streamable HTTP at `/mcp` and delegates authorization, scope checks, graph mutations, catalog
access, and task lifecycle operations to the private Gateway facade at
`/internal/ai-mcp/v1/*`.

The adapter has no database, volumes, connection drivers, secret-decryption key, or direct access
to Valkey and Orchestrator. Its Python 3.13 image installs only the dependencies from this
directory, including `mcp==2.0.0`, so Gateway dependency versions remain isolated.

## Projects and schedules

If it is unclear whether the user wants an existing or a new project, ask before changing anything.
Explicit intent needs no repeat confirmation. Never reuse a similar project in place of creating
a requested new one. `create_project(name, folder_id=None)` creates an empty project owned by the
token's user in their organization; the name must be non-empty. The token must have
`projects.mode=all`; selected-project tokens receive `SCOPE_DENIED`. Folder access follows the
ordinary Gateway rules. Read the new project's graph before validating/applying graph changes.

Schedule tools require ADMIN/SUPERADMIN and access to the project through both the user and token:

| Tool | Behavior |
| --- | --- |
| `list_project_schedules(cursor=None, limit=50)` | Paginated accessible schedules, including disabled ones. |
| `get_project_schedule(project_id)` | Settings, next run, recent runs and latest retry chain; `schedule: null` if absent. |
| `set_project_schedule(project_id, cron, ...)` | Create or replace settings and immediately enable the schedule. |
| `update_project_schedule(project_id, patch)` | Change supplied settings, preserving omitted values and enabled state. |
| `set_project_schedule_enabled(project_id, enabled)` | Enable or disable an existing schedule without replacing its settings. |

Cron uses five fields in **UTC**. Ask for the user's timezone when local-time intent is ambiguous.
Settings follow Scheduler defaults: `force_exec=false`,
`max_retries=0` (0–10), `retry_delay_seconds=60` (1–86400),
`retry_backoff="fixed"` (or `"exponential"`), `retry_max_delay_seconds=3600` (1–86400).
For exponential backoff the maximum delay must be at least the base delay.
An update patch must be non-empty; omit unchanged settings, never pass null.
Use the enabled tool rather than a `disabled` patch field.

Activation and changes to enabled schedules check graph connection access, as manual MCP runs do.
Disabling remains possible when connections are unavailable. It cancels the scheduler retry chain
and prevents future scheduled attempts; stopping a running task is a separate task operation.
Schedules persist independently of the MCP token's lifetime, using existing Scheduler semantics.

Mutations return Scheduler confirmation. Read back with `get_project_schedule` to verify settings
and `next_run_time`; a schedule-only change does not require an immediate project run.
Missing schedules on update/toggle return `SCHEDULE_NOT_FOUND`, invalid settings return
`INVALID_ARGUMENTS`, insufficient role/scope returns `SCOPE_DENIED`, inaccessible projects return
`PROJECT_NOT_FOUND_OR_DENIED`, and service failures return `SCHEDULER_UNAVAILABLE`.

## Node documentation

Use `search_nodes` to discover suitable nodes, then read `get_node_definition` before first
configuring each selected type. Its machine schema supplies types and allowed values; colocated
documentation explains selection, configuration, outputs, limitations, examples and common errors.
Consult it again when a parameter or failure is unclear.

Gateway reads `README.md` (English) and `README.ru.md` (Russian) from the installed node package.
Pass `locale="ru"` for Russian; an absent translation or unsupported locale falls back to English.
For an available node without a README, `documentation` remains `null`; unavailable nodes retain
the existing access/error behavior. Documentation ships with the matching code version.

A non-empty `search_nodes.query` also searches README text in the requested locale (with the same
fallback). Results contain compact summaries, never the complete README. Full text is returned
only by `get_node_definition` for a specific node. JSON examples contain parameter values without
an MCP request envelope; required graph edges are described separately.

All built-in node inputs, including inherited and hidden fields, provide `agent_description`:
non-localized guidance about prerequisites, value selection and configuration mistakes. This also
covers experimental, deprecated, testing and internal packages. The localized `description` remains
the UI help text. Agents should read both and consult the node README for interactions and examples.
The field stays optional for extensions and older definition payloads; when it is absent or null,
use the existing description and README. Nested input schemas may carry the same
`agent_description` metadata on their properties.

General server instructions and graph-patch schemas are independent of concrete node classes.
Node-specific configuration guidance belongs to the node's fields and colocated documentation.
Optional inputs can still require a deliberate choice; omitting them follows the documented
behavior, not a universal policy to skip configuration.

## Database comments

`browse_database` includes an optional `comment` on table/view items.
`get_database_table` includes `item.comment` and `item.columns[].comment`, so agents can
interpret tables and columns using source documentation. These fields are available through
the corresponding public Gateway catalog endpoints as well.

PostgreSQL, MySQL/MariaDB, SQL Server (`MS_Description`), Oracle and ClickHouse comments are
read from the source. Missing/empty or unsupported comments (including SQLite) are `null`.
Non-empty text is preserved, including Unicode and line breaks. If a separate optional comment
query fails, available structure is still returned and a safe warning is logged.
Catalog comments follow the existing cache TTL and refresh operation.

`ReadTableFromDBV3` preserves source table/column comments in its output metadata during full
reads, metadata-only execution and execution-cache restoration. Older node metadata without
these fields remains readable; refresh metadata or rerun the node to obtain comments.
Propagation through transform nodes and creating/updating/deleting comments are outside this
read-only feature.

## Preparing write targets

Use scoped MCP DDL for one-time preparation before applying/running the graph. Configure the
writer with an explicit column mapping; no DDL node or signal dependency is needed for that setup.

- `resolve_write_columns` is read-only. Pass the known DataFrame metadata, target and optional
  mapping/policies. Use `typed_create` before creating a missing table and `existing_table` for
  an existing one. It returns effective mapping, differences, diagnostics and suggested actions.
  Use it on initial writer setup or schema changes, not before every unchanged pipeline run.
- `create_database`, `create_schema`, `create_table` prepare missing objects.
  Existing objects are unchanged; create_table does not update their columns.
- `apply_table_column_actions` supports add/drop/recreate, comments and nullability.
  Preview every batch with `dry_run=true` (MCP default), review SQL/diagnostics, then apply the
  same batch explicitly with `dry_run=false`. During preview, applied_actions describes planned
  actions and table_metadata is absent; apply returns refreshed table metadata. Reread the
  catalog and resolve mapping again after changes. Preview alone needs no repeat user approval.

Suggestions do not authorize destructive changes. Drop/recreate require explicitly agreed data
loss; recreate_column drops and adds the column, rather than converting existing values.
For comment deletion supply explicit `comment: null`. set_column_nullable requires an explicit
boolean and no column/comment fields. Preview does not scan data for NULLs; apply checks them
before the first DDL when tightening nullable. Pause concurrent ClickHouse writes for that change.
DDL may partially commit depending on dialect: after failure or timeout, inspect the target and
plan remaining actions instead of blindly replaying a batch. Apply attempts invalidate the
catalog even on failure; preview and resolution do not.

Use runtime DDL nodes only when schema changes belong to execution or MCP lacks the required
operation. Discover specialized nodes first; justify generic SQL fallback and enforce execution
ordering. The MCP adapter has no arbitrary write-SQL tool, table truncation/recreation tool, or
new connection privileges. New arguments are typed transport models; Gateway owns execution and
validates its existing DDL contracts. Invalid arguments return INVALID_ARGUMENTS at the private
facade; execution failures remain redacted DDL_OPERATION_FAILED/DDL_UNSUPPORTED errors.

## Configuration

The service is opt-in. `DVT_AI_MCP_ENABLED` defaults to `false`; in that state the
`dvt-ai-mcp` Compose profile is inactive, Gateway does not register MCP token/internal routes,
and the proxy returns `404` for `/mcp`.

To enable it, set both:

- `DVT_AI_MCP_ENABLED=true`;
- `DVT_AI_MCP_INTERNAL_SECRET`: shared Gateway-to-adapter secret, at least 32 characters.

The installation manager and `install.sh --enable-ai-mcp` activate the `ai-mcp` Compose profile
automatically. For a direct Compose invocation, set `COMPOSE_PROFILES=ai-mcp` or pass
`--profile ai-mcp`. Disabling the option during an installation/update also stops and removes a
previously running adapter container.

GitLab deploy jobs map the environment-specific variables
`DVT_<ENV>_AI_MCP_ENABLED` and `DVT_<ENV>_AI_MCP_INTERNAL_SECRET`
(`DEV`, `PREPROD`, `DEMO`, or `PROD`)
to the runtime settings. An unset enable flag is treated as `false`.

Other required production settings:

- `DVT_PUBLIC_URL`: one or more semicolon-separated public DVT URLs used for exact Host and
  Origin allowlists.

Optional settings:

- `DVT_AI_MCP_GATEWAY_URL` (default `http://gateway:8000`);
- `DVT_AI_MCP_HOST` (default `0.0.0.0`);
- `DVT_AI_MCP_PORT` (default `8000`).

When the service is enabled, the installation manager generates a missing internal secret and
preserves an existing one during updates. It must never be reused as a user MCP token or exposed
outside the DVT service network.

## Codex

Create a purpose-bound MCP token through `POST /api/mcp-tokens`, copy the returned token once, and
store it in an environment variable. A Codex configuration is:

```toml
[mcp_servers.dvt]
url = "https://<dvt-host>/mcp"
bearer_token_env_var = "DVT_MCP_TOKEN"
default_tools_approval_mode = "writes"
tool_timeout_sec = 60
```

The service contains 31 tools for project and graph discovery, node search, atomic graph validation
and patching, server-side graph layout, SQL/file catalogs, bounded read-only previews, scoped idempotent creation of missing
databases/schemas/tables, read-only write-column resolution and preview/apply column actions,
project creation, scheduling, and task lifecycle.
It does not expose arbitrary write SQL, MCP resources or prompts, OAuth, stdio, legacy SSE,
project update/deletion, folder management, subgraph CRUD, schedule deletion, connection CRUD,
Kafka/queue connectors, or file writes.


## Graph identities and layout

New nodes require a patch-local `ref`, not a permanent `id`. References must contain a
non-whitespace character, be at most 255 characters long, and be unique within `add_nodes`.
An edge endpoint is exactly one of `{"ref": "source"}` (a new node in this patch) or
`{"id": "node_existing"}` (an existing node). Identical strings in these two namespaces
do not collide. Updates/deletions continue to address existing permanent IDs.
References are not substituted inside input values, expressions, SQL, or Python.

For example, this patch creates a small conversion pipeline:

```json
{
  "add_nodes": [
    {
      "ref": "source",
      "node_type": "JsonToDataFrame",
      "inputs": {"json": {"kind": "constant", "value": [{"value": 1}]}}
    },
    {"ref": "sink", "node_type": "DataFrameToJson"}
  ],
  "add_connections": [
    {
      "source": {"ref": "source"},
      "source_output": "output",
      "target": {"ref": "sink"},
      "target_input": "df"
    }
  ]
}
```

Pass the same patch and current `expected_graph_revision` / `expected_graph_etag` to
`validate_graph_changes`, then `apply_graph_changes`. Validation writes nothing and returns
`valid`, warnings, and a `preview` with created refs, change counts, and moved node references /
subgraph IDs. The old `preview_graph_etag` has been removed: temporary graph identities are not
the eventual stored graph.

After successful validation during apply, Gateway creates `node_<uuid>` and `edge_<uuid>`
identities, saves the graph, and returns `node_ids_by_ref` together with the usual operation
result and actual revision/etag. Existing graph IDs are preserved without migration.
Errors/warnings address new nodes using `node_ref`; mixed node lists use `{ref}` / `{id}`
selectors. Invalid added edges may be identified by their zero-based `connection_index`.
Duplicate refs, unknown references, references to deleted nodes, caller-supplied IDs on additions,
and input positions are rejected. This replaces the previous contract without a compatibility mode.

Both validate and apply check every edge in the resulting graph against the node definitions.
Unknown ports produce `UNKNOWN_SOURCE_OUTPUT` / `UNKNOWN_TARGET_INPUT` inside
`GRAPH_VALIDATION_FAILED`, with the node, `endpoint`, `port`, and either `connection_index`
for an added edge or `connection_id` for an existing edge. No changes or tasks are saved.
An already stored invalid edge blocks patches that leave it in place; a patch removing the edge
can pass because validation inspects the resulting graph. Known data, signal, and variable ports
remain supported; pipeline validation still checks type compatibility.

After a timeout, reread the graph before planning remaining changes; never blindly recreate nodes
with refreshed concurrency tokens.

Agents cannot supply positions for either added or updated nodes. Structural edits automatically
rearrange affected connected components, considering both the original and resulting graph.
All edge types participate. Affected subgraphs and all their members move together; unrelated
components retain their positions. Parameter/comment-only edits do not cause layout.
The geometry and requested changes are persisted together; `GRAPH_LAYOUT_FAILED` aborts the patch.

Layout uses deterministic layers directed left to right, branch ordering, cycle condensation,
and collision avoidance against unchanged components. Cycles can be drawn but do not bypass
pipeline validation. Node size is estimated as a fixed 360 × 240 with gaps of 140 between layers,
80 between nodes, and 120 between components. Expanded panels use UI padding and a minimum
520 × 340; collapsed panels occupy 360 × 160. The server stores absolute node/group positions,
not measured browser sizes. Actual oversized UI cards can still overlap; this is not pixel parity
with the UI's ELK layout.

### Arrange an existing project

`auto_layout_project(project_id, expected_graph_revision, expected_graph_etag, dry_run=true)`
arranges the entire project, including subgraphs and isolated nodes. Preview returns
`moved_node_ids`, `moved_subgraph_ids`, `changes_count`, `bounds`, and current revision/etag.
Apply with `dry_run=false` and the same tokens; a concurrent edit requires a new preview.
No additional user confirmation is required when layout is already within the authorized task.

This operation checks access and structural references, but does not require configured inputs
or installed node extensions. Empty projects are accepted. It updates only changed coordinates,
does not execute pipelines or metadata inference, and leaves computational revision/dirty state
unchanged. The graph etag reflects changed positions. A no-op performs no graph writes.
Creating, deleting, or editing subgraph properties through MCP remains unsupported; automatic
movement of existing subgraphs is allowed.
