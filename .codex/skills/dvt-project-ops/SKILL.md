---
name: dvt-project-ops
description: "Operate and diagnose a local Visual_transformer checkout: inspect or restart Docker services, query internal logs and task execution state, prepare DB connection test fixtures, and append the agent changelog. Do not use for end-user graph/catalog/task lifecycle operations owned by dvt_ai_mcp."
---

# DVT Project Ops

Use the bundled scripts for DVT-specific operations that would otherwise require learning internal
service names, database tables, connection ownership, or connector behavior. Run every Python
script with the project virtual environment and from the repository root.

## Runtime Services

Use `scripts/runtime_services.py status` to inspect the Docker development stack. Restrict the
result with repeated `--service` options when only selected services matter.

Use `scripts/runtime_services.py restart <service>` only when the user requested a restart or it is
a normal required step after an authorized code change. The helper verifies the post-restart
state. It does not inspect or restart processes launched directly by an IDE or terminal.

The default stack is `dev`. Pass `--stack production` only when the root production-like Compose
stack is the intended target.

## Logs And Tasks

Use `scripts/diagnostics.py logs` for internal, cross-service diagnostics. Prefer narrow filters
such as `--task-id`, `--project-id`, `--service-name`, or `--message`; keep pagination bounded.
Messages and tracebacks are secret-redacted before output.

Use `scripts/diagnostics.py tasks` for queue/lifecycle discovery and
`scripts/diagnostics.py task <task-id>` for one execution with log-derived node order and processed
nodes. Use `dvt_ai_mcp` instead when acting as an end user who needs scoped project execution,
waiting, cancellation, or user-facing task logs.

## DB Test Fixtures

Read [references/db-fixtures.md](references/db-fixtures.md) before creating, checking, or seeding a
connection. These commands can access external systems and mutate the local DVT database or a
target database. Do not treat loading this skill as authorization for those mutations.

Use `scripts/db_fixtures.py` only for developer/test setup:

* `create --spec <path>` creates a connection owned by the default privileged service user.
* `check --connection-id <id>` checks a stored connection.
* `check --spec <path>` checks a transient connection without storing it.
* `seed --connection-id <id>` creates and fills the bounded sample table.

Never place secret values in command arguments or the spec. Refer to secret-bearing environment
variables through `secrets_from_env`. Output is always masked and redacted.

`seed --if-exists truncate|drop` is destructive. Require explicit user authorization immediately
before running it and pass `--allow-destructive`; otherwise leave the default `fail` behavior.

## Changelog

After repository code or documentation changes, append one concise Russian entry with:

```powershell
<venv>\Scripts\python.exe .codex/skills/dvt-project-ops/scripts/append_changelog.py --text "Описание изменений."
```

Pass only entry text. The helper owns timestamp and Markdown formatting.

## Ordinary Commands

Do not recreate generic wrappers. Run Python files, unit tests, Ruff, and protobuf generation
directly through the project interpreter. Prefer direct-venv unit tests for fast verification; use
the existing Docker test scripts for integration and end-to-end suites that require their stack.
