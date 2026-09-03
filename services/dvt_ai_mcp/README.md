# DVT AI MCP

`dvt_ai_mcp` is the stateless MCP adapter for end users and their coding agents. It exposes
Streamable HTTP at `/mcp` and delegates authorization, scope checks, graph mutations, catalog
access, and task lifecycle operations to the private Gateway facade at
`/internal/ai-mcp/v1/*`.

The adapter has no database, volumes, connection drivers, secret-decryption key, or direct access
to Valkey and Orchestrator. Its Python 3.13 image installs only the dependencies from this
directory, including `mcp==2.0.0`, so Gateway dependency versions remain isolated.

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

The MVP contains 22 tools for project and graph discovery, node search, atomic graph validation
and patching, SQL/file catalogs, bounded read-only previews, scoped idempotent creation of missing
databases/schemas/tables for `WriteDataFrameToDBV4`, and project task lifecycle. It does not expose
arbitrary write SQL, MCP resources or prompts, OAuth, stdio, legacy SSE, project CRUD, subgraph
CRUD, schedules, connection CRUD, Kafka/queue connectors, or file writes.
