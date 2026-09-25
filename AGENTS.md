# DVT Agent Guidelines

## User Intent & Scope
- Respond in the language used by the user unless they request otherwise. This does not change explicit language requirements for repository artifacts, such as node documentation or changelog entries.
- Distinguish a question about whether a change is possible from an instruction to make that change, regardless of the working mode, including ordinary operation outside Plan Mode.
- For questions such as "Would you be able to fix this?", "Is this fixable?", or "How would you approach this?", first answer the question: explain feasibility, the proposed approach, and significant limitations. Such a question alone does not authorize file changes, implementation, or service restarts; read-only code inspection is allowed to support an informed answer.
- Start implementation when instructed to do so, for example "Fix it", "Implement it", or "Make the changes", or after the user agrees to the proposed fix. If implementation has already been authorized in the current discussion, do not request authorization again; a follow-up question does not revoke previously authorized work.
- If it is unclear whether the user wants discussion or implementation, first provide a substantive answer and clarify their intent before making changes.
- Stay within the task scope: do not perform incidental refactoring, renaming, or other improvements unless they are necessary for the requested result.
- Separate diagnosis from implementation: a request such as "Look into why this is failing" authorizes investigation. Present the identified cause and proposed fix to the user first; implement the fix once instructed to do so, unless implementation was already authorized.
- Keep small changes simple: do not introduce new abstractions, general-purpose mechanisms, or dependencies without a concrete need in the current task.
- Communicate substantively: report results, significant findings, or blockers; do not narrate every file read or command.

## Project Description
**DVT (Denvic Visual Transformer)** is a visual ETL (Extract, Transform, Load) tool designed to build, manage, and execute complex data pipelines through a node-based graphical interface. This repository contains the backend system, which orchestrates pipeline execution across a distributed set of microservices.

The core architecture includes:
- **Gateway API** that serves as the primary entrypoint for the frontend, handling user authentication, project management, pipeline definitions, and real-time WebSocket communication.
- **Orchestrator** is a gRPC service that accepts tasks, monitors worker heartbeats, publishes dispatch messages from the durable outbox, and reconciles task lifecycle state.
- **Task Workers** consume Celery messages, atomically claim tasks in PostgreSQL, and execute pipelines with concurrency `1` per container.
- **Project Scheduler** that manages scheduled pipeline execution tasks.

The system is built to be scalable and modular, featuring a custom Node Domain-Specific Language (DSL) that allows developers to easily extend its capabilities by adding new data sources, transformations, and destinations.

## Deployment Context & Design Principles
- The effective production environment for DVT is a customer-installed DVT instance. In most cases, one customer corresponds to one deployed DVT instance running on the customer's own infrastructure.
- Because DVT is deployed on customer-managed infrastructure, operational simplicity matters. When making architecture or delivery decisions, prefer fewer services and fewer Docker containers unless extra decomposition has a clear, justified payoff.
- Treat container/service count as a real product constraint, not just an implementation detail. If two approaches are otherwise comparable, prefer the one with the smaller deployment footprint.

## Task Execution Architecture

- PostgreSQL (`tasks` plus `task_dispatch_outbox`) is the authoritative task lifecycle state; Celery/Valkey provide transport and telemetry only.
- Orchestrator never predicts or assigns a concrete worker for ordinary dispatch. Celery selects an available homogeneous worker, which records its actual ID during atomic claim.
- A Task Worker container has exactly one pipeline execution slot (`prefork`, concurrency `1`, no task prefetch reservation). Worker loss is reconciled as `WORKER_LOST`; Celery must not automatically rerun a non-idempotent pipeline.
- User `STOP` is cooperative: PostgreSQL `CANCEL_REQUESTED` is authoritative, the worker observes it through the cancellation transport and passes `TaskStopEvent` to `PipelineProcessor`. The Orchestrator escalates an unfinished user STOP after `TASK_STOP_GRACE_PERIOD_SEC`; immediate `HARD_STOP` uses Celery remote control.
- Project Scheduler remains the owner of scheduled retry policy; `task_execution` does not retry scheduled jobs itself.
- `WORKER_LOST` recovery is PostgreSQL-driven for worker-owned `STARTED`/`RUNNING` executions. In-memory execution telemetry is only an auxiliary/cache signal; after an Orchestrator restart, live workers get one heartbeat timeout to re-register before absence is treated as worker loss.
- Root task coalescing is based on persisted `(queued_at, task_id)` under project-scoped DB serialization: only the freshest `API`/`SCHEDULER` root execution stays runnable; `NODE` child executions are never superseded by this rule.
- Extension execution readiness requires `is_installed && is_enabled && deps_status == READY`. Linux Task Workers preload built-in/extension registries in the warm prefork MainProcess and recycle the execution child after every Celery task. If a child observes a newer authoritative extension runtime generation, it reloads that generation for the current task and requests a safe parent refresh: task queues are drained, the pool is reduced to zero, the warm registry is refreshed, then the single execution slot is restored. Native Windows development defaults to the `solo` pool because Celery prefork/Windows spawn is not a supported production-equivalent runtime.
- Synchronous nested waits reserve at most `alive_workers - 1` slots. Capacity reconciliation is atomic and deterministic; if alive capacity shrinks, newest reservations fail first so at least one worker slot can be released.
- Termination-reason precedence belongs to `task_execution/domain`; system failures such as `OOM_GUARD`, `WORKER_LOST`, and nested-wait capacity loss must end as `ERROR`, while user STOP/HARD_STOP end as `CANCELLED` unless superseded by a stronger reason.

## Project Structure & Module Organization
- `src/`: Contains the core domain logic.
  - `modules/task_execution/`: DDD-lite bounded context for authoritative task lifecycle, durable dispatch, claim and execution transport contracts.
  - `node_dsl/`: Primitives and helpers for the custom Node DSL.
  - `nodes/`: Implementations of individual ETL nodes built on top of the Node DSL.
  - `pipeline/`: Code for pipeline orchestration, validation, and execution logic.
  - `clients/`: Integrations with external services (e.g., other DVT microservices, databases).
  - `crud/`: Data persistence logic for interacting with the database.
  - `caching/`, `db/`, `infra/`, `managers/`, `runtime/`: Infrastructure, runtime wiring, and shared execution helpers.
  - `models/`, `schemas/`, `dto/`: SQLModel models, Pydantic schemas for API validation, and Data Transfer Objects.
- `core/`: Reusable infrastructure primitives, such as database engines, hashing utilities, and storage abstractions.
- `services/`: Deployable microservice entrypoints.
  - `dvt_ai_mcp/`: Stateless user-facing MCP adapter that exposes scoped DVT project, graph, connection catalog, and task execution tools through the private Gateway facade.
  - `gateway/`: The main FastAPI application that exposes the REST API and WebSocket endpoints to the frontend.
  - `orchestrator/`: gRPC service that owns durable dispatch, heartbeat observation and lifecycle reconciliation.
  - `task_worker/`: A one-slot Celery execution container that atomically claims and runs pipeline tasks.
  - `project_scheduler/`: A service for managing scheduled (cron-based) project runs.
  - `task_benchmarking/`: Benchmark runner for pipeline execution time and memory profiling.
  - `ui/`: The frontend application (Vite-based), providing the visual node editor.
  - `proxy/`: An Nginx reverse proxy that routes API requests to the `gateway` and serves the `ui`.
  - `tester/`: CI helper image for running tests in a controlled environment.
- `scripts/`: Command-line helpers split into `scripts/services/` (service entrypoints), `scripts/docker/` (Docker/dev/test flows), and `scripts/misc/` (maintenance utilities).
- `tests/`: Unit, integration, and end-to-end tests, mirroring the structure of the `src/` directory.
- `migrations/`: Alembic database migration scripts.
- `locales/`: Internationalization (i18n) resource files for multi-language support.
- `.codex/skills/dvt-project-ops/`: Project skill for local Docker operations, internal diagnostics, DB test fixtures, and agent changelog updates.
- **Configuration & Runtime**:
  - `docker-compose.yaml`: Root production-like compose file.
  - `docker/docker-compose.*.yaml`: Development, override, and testing compose files.
  - `docker/docker-bake.release.hcl`: Docker Buildx Bake release overlay for pipeline-specific candidate tags and release-only build overrides. Local Compose may use `UI_BUILD_CONTEXT`; official release candidate Bake always builds UI from the pinned `services/ui` submodule, pushes candidates to `cr.distribution.denvic.tech/dvt/*`, records their immutable digests, integration-tests backend candidates by `@sha256`, then promotes those tested remote manifests without rebuild.
  - `config.py`: Centralized configuration management, loading settings from environment variables.
  - `requirements.txt`: Python package dependencies for various services.
  - `logging.yaml`: Configuration for the logging system.

## Agent Changelog
Changelog entries must be appended through `.codex/skills/dvt-project-ops/scripts/append_changelog.py` instead of manual file editing. The agent should pass only entry text, while the helper adds the current timestamp and writes the entry to `AGENTS_CHANGELOGS.md`.

Changelog entry requirements:
- Entry text must clearly and concisely describe the changes.
- **All changelog entries must be written in Russian.**

Example entry content in English for reference (write the actual entry in Russian):
```text
Updated `AGENTS.md` to improve the project description and structure.
Added instructions for the `dvt-project-ops` project skill.
```
This process ensures a transparent and traceable history of automated code modifications.

## Experiment Guidelines
When running optimization experiments for the project, read and follow `services/task_benchmarking/README.md` before starting the experiment workflow.
`experiments/` is reserved for experiment reports only; do not store random files there.

## File System Access
For working with the repository file system, the agent must use the `filesystem` tool (read/write/list/edit) as the primary interface instead of shell commands where possible. Use shell commands only when the `filesystem` tool cannot perform the required operation.

## Gateway/OpenAPI & UI Rules
- After changing entities (models or data schemas) used by the Gateway API (`services/gateway`), restart the `Gateway` service because `services/ui/src/shared/gatewayClient` is generated automatically from the Gateway OpenAPI schema.
- Do not edit `services/ui`: local UI development takes place in a separate directory.
- If a route implementation becomes too large, extract supporting modules into separate files and organize the directory as a package instead of expanding a single file in `services/gateway/routes/impl`.
- In such a package, name the main implementation file `impl.py` and keep `__init__.py` as a thin facade that re-exports public entrypoints.

## DDD-lite Rules For `src/modules`
- The rules in this section are mandatory for bounded context modules under `src/modules/*`.
- `domain` contains only business concepts: entities, value objects, domain types/enums, policies, domain exceptions, and repository/gateway contracts.
- `flow` contains only application orchestration and use cases, operating through domain contracts and domain objects.
- `infra` contains only technical details: ORM/SQLModel models, Pydantic/transport schemas, HTTP/DB clients, repository/gateway implementations, and mappers.
- `domain` must not import `flow`, `infra`, `src.models`, `src.schemas`, `src.dto`, `src.crud`, `src.clients`, `src.db`, `fastapi`, `pydantic`, `sqlmodel`, or `sqlalchemy`.
- `flow` must not import `infra`, `src.models`, `src.schemas`, `src.dto`, `src.crud`, `src.clients`, `src.db`, `fastapi`, `pydantic`, `sqlmodel`, or `sqlalchemy`.
- `infra` may import `domain`, but must not import `flow`.
- Declare repository/gateway contracts only in `domain`.
- Do not create `repositories` or `gateways` inside `flow`. Protocols belong in `domain`; implementations belong in `infra`.
- Repository/gateway contracts must accept and return only domain entities, value objects, domain result objects, primitives, or standard-library types.
- `Pydantic`, `SQLModel`, HTTP schemas, ORM rows, DB sessions, and transport DTOs are forbidden in domain contract signatures.
- Domain entities and value objects must use `dataclass` by default. Another type is allowed only when the reason is explicitly documented in the code or task.
- `ORM <-> domain` and `transport <-> domain` conversions belong only in `infra/mappers.py` or adjacent infrastructure modules.
- If a use case needs data from a database or HTTP service, `flow` must obtain it through a domain contract, never directly through `crud` or a client.
- All use cases in `flow/use_cases` must be classes, not functions. Their main entrypoint must be named `execute`.
- Do not use or raise `RegisteredException` directly outside a layer-specific `exceptions.py`. If a layer needs an error, create `exceptions.py` in that layer and declare a named subclass of `RegisteredException`.
- Do not overload repository contracts with methods better expressed as separate use cases. A growing contract is a signal to reconsider the aggregate boundary or move orchestration into `flow`.
- Do not violate DDD-lite boundaries for speed, migration compatibility, or temporary simplification.
- Compatibility shims are allowed only outside the bounded context module to support legacy callers. A shim must not introduce infrastructure or framework dependencies into `domain` or `flow`.
- If a correct implementation would require violating these boundaries or makes layer ownership ambiguous, stop and ask the user for a decision instead of making an assumption.

## Node Package Contract
- Each built-in DVT node lives in a separate package at `src/nodes/<category>/<node_package>/`: one package represents one registrable node.
- `node.yaml` is required and is the only filesystem marker used for discovery; V1 contains `schema_version: 1`.
- The package's `__init__.py` must export `NODE_CLASS`, pointing to a concrete `BaseNode` subclass from that package.
- Category `__init__.py` files must not import nodes or perform eager registration; category barrel modules are forbidden.
- Shared helpers for a category belong in `_shared/`; private directories whose names start with `_` are excluded from discovery.
- Each new active built-in node must include `README.md` (canonical English) and an equivalent `README.ru.md` translation in its package; the template and rules are in `src/node_dsl/README.md`.
- For this requirement, active nodes are public, stable nodes without `DISABLED=True`, `DEPRECATED=True`, `VISIBLE=False`, or `EXPERIMENTAL=True`, and without the tags `Deprecated`, `Testing`, `Unstable`, or `Not tested`. Internal/test nodes and Kafka nodes excluded from MCP are out of scope. Local node-disable settings do not change this scope; extension documentation is maintained separately.
- When changing a node's behavior, parameters, or limitations, review and update both README versions. Examples, port names, and expected results must match the current implementation and machine-readable schema.
- READMEs must describe actual behavior; record discovered defects separately. Documentation ships with the code; separate documentation versioning and mandatory CI checks for documentation coverage are not required.

## Project Skill (`dvt-project-ops`)
Use `.codex/skills/dvt-project-ops` for DVT-specific local development operations that require knowledge of repository internals: Docker service status/restart, cross-service log and task diagnostics, safe DB connection test fixtures, and changelog appends.

For user-facing DVT project, graph, catalog, connection and task operations through MCP, read the shared `.agents/skills/dvt-mcp-projects/SKILL.md` and its relevant references. This applies to any AI agent working in this repository.

Usage rules for agents:
- Read the skill before using its scripts and run them through the project virtual environment from the repository root.
- Use `dvt_ai_mcp` for user-facing scoped project, graph, connection catalog, and task lifecycle operations; do not duplicate those capabilities in the project skill.
- Runtime helpers are Docker-only. IDE- or terminal-launched process inspection and the removed custom PyCharm plugin are not supported.
- Do not add generic wrappers for Python execution, pytest, Ruff, or protobuf generation; run their existing commands directly.
- After editing the skill, run the `skill-creator` validator and its unit tests, and keep this section synchronized with its current capabilities.

## Environment Setup
Always execute Python scripts through the project virtual environment. Prefer resolving it via `DVT_VENV_PATH` (it may point either to the venv directory or directly to `python.exe`); otherwise use the local venv directory configured in your environment and ensure `PYTHONPATH` includes the absolute project root before launching any script. Activate via `source <venv_dir>/Scripts/activate` (Git Bash) or `.\<venv_dir>\Scripts\activate` / `.\<venv_dir>\Scripts\Activate.ps1` (PowerShell), or call `<venv_dir>/Scripts/python.exe` directly. Install deps with `pip install -r requirements.txt`; copy or recreate the venv only when rebuilding it.

## Build, Test, and Development Commands
- `<venv_dir>/Scripts/python.exe -m scripts.services.run_gateway`: start the FastAPI gateway.
- `<venv_dir>/Scripts/python.exe -m scripts.services.run_task_worker`: run the background worker.
- `<venv_dir>/Scripts/python.exe -m scripts.services.run_project_scheduler`: run the project scheduler.
- `<venv_dir>/Scripts/python.exe -m scripts.services.run_orchestrator`: run the orchestrator service.
- `docker compose --project-directory . -f docker/docker-compose.base.yaml -f docker/docker-compose.dev.yaml up --build`: bring up the dev stack.
- `docker compose --project-directory . -f docker/docker-compose.base.yaml -f docker/docker-compose.dev.yaml -f docker/docker-compose.tests.yaml --profile testing up tester_unit`: run CI-parity test services.
- `<venv_dir>/Scripts/python.exe -m pytest` with optional `-k` or `-m docker_required`: run tests directly from the venv.
- `<venv_dir>/Scripts/python.exe -m contracts.tools.gen_protos`: regenerate gRPC code after proto changes (set `PYTHONIOENCODING=utf-8`).

## Coding Style & Naming Conventions
Use 4-space indents, ~100 character lines, snake_case for functions/modules, PascalCase for classes, uppercase constants, and intentful node names (`WriteDataFrameToDB`). Prefer dataclasses for domain entities/value objects in `src/modules`, and use Pydantic only for transport, API validation, configuration, and infrastructure boundaries.

## Testing Guidelines

### Proportionate Verification
- Choose verification based on the risk of the change and the affected behavior. Adding tests and running test suites are not mandatory rituals after every edit.
- For changes limited to documentation, agent instructions, comments, text, or formatting with no behavior change, reviewing the diff and checking consistency is sufficient. Do not write tests for the presence of phrases, headings, or exact documentation wording.
- For logic changes, use relevant existing tests first. Add a new test when it protects a meaningful scenario or edge case, or reproduces a real defect not covered by existing tests.
- Do not add tests that duplicate the implementation or only check mock configuration, trivial assignments, or internal structure without meaningful observable behavior. Do not expand coverage of unrelated code as part of the current task.
- Start with the smallest relevant set of checks. Run the full suite, Docker-based tests, integration tests, or end-to-end tests when the change affects the corresponding boundaries, there is a concrete regression risk, or the task or mandatory project checks explicitly require them.
- After verification succeeds, do not repeat or broaden it without new changes, failures, or a concrete unverified risk. In the final response, briefly state what was checked or why tests were unnecessary.

Keep tests beside code in `tests/` (files `test_<module>.py`), reuse `tests/fixtures/` and `tests/data/`, mark Docker suites with `@pytest.mark.docker_required`, and cover pipeline edges and client fallbacks.

### Test Development Rules
- `tests/unit` — unit tests. Use mocks for any external connections or an SQLite database when persistence is required.
- `tests/integration` — integration tests. Use `testcontainers` instead of mock fixtures.
- `tests/e2e` — end-to-end tests. Keep scenarios close to real service wiring and reuse shared Docker fixtures.
- File structure must mirror source layout:
  - `core/storage/index/base_key.py` → `tests/unit/core/storage/index/test_base_key.py` or `tests/integration/core/storage/index/test_base_key.py`
  - `src/package/module.py` → `tests/integration/src/package/test_module.py`
- It is allowed to split a single module into multiple test files, for example:
  - `src/package/complex_module.py` → `tests/integration/src/package/module/test_fn_name.py`, `tests/integration/src/package/module/test_class_name.py`

## Commit & Pull Request Guidelines
Follow prefixes (`ADD`, `UPD`, `FIX`, `CLR`) plus a present-tense summary (e.g. `UPD pipeline validation for Celery`). Keep commits focused, list verification steps (pytest etc.), link issues, add evidence when useful, and request review from the owning service lead.

## Security & Configuration Tips
Store secrets in env vars or `.env` files kept out of git. Review `logging.yaml` before enabling verbose sinks, and avoid committing local environments.
