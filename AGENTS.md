# DVT Agent Guidelines

## Project Description
**DVT (Denvic Visual Transformer)** is a visual ETL (Extract, Transform, Load) tool designed to build, manage, and execute complex data pipelines through a node-based graphical interface. This repository contains the backend system, which orchestrates pipeline execution across a distributed set of microservices.

The core architecture includes:
- **Gateway API** that serves as the primary entrypoint for the frontend, handling user authentication, project management, pipeline definitions, and real-time WebSocket communication.
- **Orchestrator** gRPC сервис принимает задачи, отслеживает heartbeat воркеров, публикует durable dispatch outbox и выполняет reconciliation lifecycle.
- **Task Workers** consume Celery messages, атомарно claim-ят task в PostgreSQL и выполняют pipeline с concurrency `1` на container.
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
- Extension execution readiness requires `is_installed && is_enabled && deps_status == READY`. Persistent Task Worker children compare an authoritative extension runtime generation before each claimed task and reload local dependencies/node registry only when that generation changes.
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

Example entry text:
```text
Обновлен файл `AGENTS.md` для улучшения описания проекта и структуры.
Добавлены инструкции по project skill `dvt-project-ops`.
```
This process ensures a transparent and traceable history of automated code modifications.

## Experiment Guidelines
When running optimization experiments for the project, read and follow `services/task_benchmarking/README.md` before starting the experiment workflow.
`experiments/` is reserved for experiment reports only; do not store random files there.

## File System Access
For working with the repository file system, the agent must use the `filesystem` tool (read/write/list/edit) as the primary interface instead of shell commands where possible. Use shell commands only when the `filesystem` tool cannot perform the required operation.

## Gateway/OpenAPI & UI Rules
- При изменении сущностей (моделей, схем данных), задействованных в Gateway API (`services/gateway`), необходимо перезапустить сервис `Gateway`, так как `services/ui/src/shared/gatewayClient` генерируется автоматически по OpenAPI от `Gateway`.
- Не вносить правки в `services/ui`: локальная разработка UI ведется в другой директории.
- Если имплементация роута становится слишком большой, не раздувать один файл в `services/gateway/routes/impl`: выносить вспомогательные модули в отдельные файлы и оформлять директорию как пакет.
- Для такой пакетной структуры основной файл имплементации называть `impl.py`, а `__init__.py` оставлять тонким фасадом для re-export публичных entrypoint-ов.

## DDD-lite Rules For `src/modules`
- Правила этого раздела обязательны для bounded context модулей в `src/modules/*`.
- `domain` содержит только бизнес-смысл: entities, value objects, domain types/enums, policies, domain exceptions, repository/gateway contracts.
- `flow` содержит только application orchestration/use cases и работает через domain contracts и domain objects.
- `infra` содержит только технические детали: ORM/SQLModel models, Pydantic/transport schemas, HTTP/DB clients, repository/gateway implementations, mappers.
- `domain` не импортирует `flow`, `infra`, `src.models`, `src.schemas`, `src.dto`, `src.crud`, `src.clients`, `src.db`, `fastapi`, `pydantic`, `sqlmodel`, `sqlalchemy`.
- `flow` не импортирует `infra`, `src.models`, `src.schemas`, `src.dto`, `src.crud`, `src.clients`, `src.db`, `fastapi`, `pydantic`, `sqlmodel`, `sqlalchemy`.
- `infra` может импортировать `domain`, но не импортирует `flow`.
- Repository/gateway contracts объявляются только в `domain`.
- Нельзя создавать `repositories` или `gateways` внутри `flow`. Протоколы живут в `domain`, имплементации живут в `infra`.
- Repository/gateway contracts принимают и возвращают только domain entities, value objects, domain result objects или примитивы/std-lib types.
- `Pydantic`, `SQLModel`, HTTP schemas, ORM rows, DB sessions и transport DTO запрещены в сигнатурах domain contracts.
- По умолчанию domain entities и value objects должны быть `dataclass`. Использовать другой тип допустимо только при явно описанной причине в коде или задаче.
- Преобразования `ORM <-> domain` и `transport <-> domain` живут только в `infra/mappers.py` или соседних infra-модулях.
- Если use case требует данные из БД/HTTP, `flow` должен получать их через domain contract, а не через `crud`/client напрямую.
- Все use case в `flow/use_cases` должны быть классами, а не функциями. Основная точка входа use case должна называться `execute`.
- Не использовать и не выбрасывать `RegisteredException` напрямую вне layer-specific `exceptions.py`. Если слою нужна ошибка, создать `exceptions.py` в этом слое и объявить именованный класс-наследник от `RegisteredException`.
- Не перегружать repository contracts методами, которые лучше выражаются отдельными use case. Если контракт разрастается, это сигнал пересмотреть границу агрегата или вынести orchestration в `flow`.
- Нельзя нарушать границы DDD-lite ради скорости, совместимости миграции или временного упрощения.
- Compatibility shims допустимы только вне bounded context модуля, чтобы поддержать legacy callers. Shim не должен затаскивать infra/framework зависимости в `domain` или `flow`.
- Если корректная реализация требует нарушить эти границы или делает принадлежность к слою неоднозначной, агент должен остановиться и запросить решение пользователя вместо самостоятельного допущения.

## Project Skill (`dvt-project-ops`)
Use `.codex/skills/dvt-project-ops` for DVT-specific local development operations that require knowledge of repository internals: Docker service status/restart, cross-service log and task diagnostics, safe DB connection test fixtures, and changelog appends.

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
