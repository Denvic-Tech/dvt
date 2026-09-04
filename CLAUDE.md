# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**DVT (Denvic Visual Transformer)** is a visual ETL tool for building and executing complex data pipelines through a node-based graphical interface. The system is composed of distributed microservices orchestrated through Kafka message queuing.

### Core Architecture

The system follows a **microservices architecture** with these main components:

- **Gateway** (`services/gateway/`): FastAPI application serving as the main API entrypoint. Handles authentication, project management, pipeline definitions, REST/WebSocket communication, and runs a gRPC server for log forwarding.
- **Task Worker** (`services/task_worker/`): Background service consuming Kafka jobs to execute pipeline node logic. Connects to Gateway via gRPC for log forwarding.
- **Task Scheduler** (`services/task_scheduler/`): Manages cron-based scheduled pipeline runs.
- **Store** (`services/store/`): gRPC service providing content storage and index storage for caching pipeline data.
- **UI** (`services/ui/`): Vite-based frontend providing the visual node editor.
- **Proxy** (`services/proxy/`): Nginx reverse proxy routing requests to Gateway and serving UI.

**Key Infrastructure:**
- PostgreSQL for persistence
- Redpanda/Kafka for task queuing
- gRPC for inter-service communication (Store service, log forwarding)
- WebSocket for real-time frontend updates
- S3-compatible storage (optional) for user files

### Node DSL System

The project uses a custom **Node Domain-Specific Language (DSL)** (`src/node_dsl/`) for defining ETL nodes:

- **BaseNode**: All nodes inherit from this class, which uses `BaseNodeMeta` metaclass for automatic field processing
- **InputField/OutputField**: Declarative field definitions with type resolution, validation, and UI hints
- **Node Categories**: Nodes are categorized (e.g., SqlConnectionOutputBaseNode, DFOutputBaseNode, KafkaConnectionOutputBaseNode)
- **Registry System**: Automatic registration of nodes, hooks, and localization on library import
- **Execution Flow**: `execute()` → `BEFORE_PROCESS` hook → `process()` → `AFTER_PROCESS` hook
- Node implementations live in `src/nodes/`

Key concept: The metaclass `BaseNodeMeta` processes `InputField` and `OutputField` declarations, resolves types via `TypeResolver`, and builds `_input_field_instances` and `_output_field_instances` dictionaries.

### Project Structure

```
src/
├── node_dsl/        # Node DSL framework (BaseNode, fields, metaclasses, registry)
├── nodes/           # ETL node implementations (data sources, transforms, destinations)
├── pipeline/        # Pipeline orchestration, validation, execution logic
├── clients/         # Service clients (GatewayClient, StoreClient, WSForwardClient, etc.)
├── crud/            # Database CRUD operations
├── models/          # SQLModel database models
├── schemas/         # Pydantic validation schemas
├── db/              # Database engine setup
├── logger/          # Logging configuration and sinks (DB, WebSocket)
├── caching/         # Cache management for pipeline data
├── managers/        # Business logic managers
├── runtime/         # Runtime utilities (gRPC channels, etc.)
└── utils/           # Utility functions

services/
├── gateway/         # Main API gateway FastAPI app
├── task_worker/     # Kafka consumer executing pipeline tasks
├── task_scheduler/  # Cron-based scheduler
├── store/           # gRPC storage service
├── ui/              # Frontend application
└── proxy/           # Nginx reverse proxy

scripts/             # CLI tools (migrations, user management, run services)
tests/               # Unit and integration tests
migrations/          # Alembic database migrations
locales/             # i18n resources
core/                # Reusable infrastructure (DB engines, hashing, storage)
contracts/           # gRPC protocol buffer definitions
dags/                # Airflow DAG templates
docker/              # Dockerfiles
```

## Development Environment

### Virtual Environment Setup

**CRITICAL**: Always use the `{venv_dir_path}` virtual environment (Python 3.10+):

```bash
# Activate (Git Bash)
source {venv_dir_path}/Scripts/activate

# Activate (PowerShell)
.\{venv_dir_path}\Scripts\activate

# Or call directly
{venv_dir_path}/Scripts/python.exe <script>
```

Install dependencies:
```bash
pip install -r requirements.txt
pip install -r services/gateway/requirements.txt
pip install -r services/task_worker/requirements.txt
pip install -r services/task_scheduler/requirements.txt
pip install -r services/store/requirements.txt
```

### Running Services Locally

Start infrastructure (Postgres, Redpanda):
```bash
docker compose -f docker-compose.dev.yaml up -d postgres redpanda redpanda-console
```

Run individual services:
```bash
# Gateway
{venv_dir_path}/Scripts/python.exe -m scripts.run_gateway

# Task Worker
{venv_dir_path}/Scripts/python.exe -m scripts.run_task_worker

# Task Scheduler
{venv_dir_path}/Scripts/python.exe -m scripts.run_task_scheduler

# Store Service
{venv_dir_path}/Scripts/python.exe -m scripts.run_store_service
```

Run all services in Docker:
```bash
docker compose -f docker-compose.dev.yaml up --build
```

Access points:
- Gateway API: http://localhost:8001/api/docs
- UI: http://localhost:81
- Proxy (full stack): http://localhost:80
- Redpanda Console: http://localhost:8080

### Database Management

```bash
# Run migrations
{venv_dir_path}/Scripts/python.exe -m scripts.run_migrations

# Create tables
{venv_dir_path}/Scripts/python.exe -m scripts.create_tables

# Create admin user
{venv_dir_path}/Scripts/python.exe -m scripts.create_admin

# Register user
{venv_dir_path}/Scripts/python.exe -m scripts.register_user
```

## Testing

```bash
# Run all tests
{venv_dir_path}/Scripts/python.exe -m pytest

# Run specific test file
{venv_dir_path}/Scripts/python.exe -m pytest tests/test_pipeline.py

# Run with keyword filter
{venv_dir_path}/Scripts/python.exe -m pytest -k "test_node_execution"

# Run tests requiring Docker
{venv_dir_path}/Scripts/python.exe -m pytest -m docker_required

# Run tests with infrastructure
python3 scripts/docker/unit_tests.py
python3 scripts/docker/integration_tests.py
python3 scripts/docker/e2e_tests.py
```

Test organization:
- Tests mirror `src/` structure in `tests/`
- Fixtures in `tests/fixtures/`
- Test data in `tests/data/`
- Mark Docker-dependent tests with `@pytest.mark.docker_required`

## Code Quality

```bash
# Lint
{venv_dir_path}/Scripts/python.exe -m ruff check src tests

# Format
{venv_dir_path}/Scripts/python.exe -m ruff format src tests

# Type checking
{venv_dir_path}/Scripts/python.exe -m mypy src tests
```

### Coding Standards

- **Indentation**: 4 spaces
- **Line length**: ~100 characters (E501 ignored in ruff)
- **Naming**: snake_case (functions/variables), PascalCase (classes), UPPER_CASE (constants)
- **Node naming**: Intentful, descriptive (e.g., `WriteDataFrameToDB`, not `DBWriter`)
- **Type hints**: Required (mypy strict mode enabled)
- **Imports**: Managed by ruff, sorted with isort

## Key Development Patterns

### Creating New Nodes

1. Create `src/nodes/<category>/<node_package>/` with `__init__.py`, `node.py`, and `node.yaml` (`schema_version: 1`).
2. Inherit from the appropriate base class (e.g., `DFOutputBaseNode` for DataFrame output) and keep one registered DVT node per package.
3. Re-export the public class from the package `__init__.py` and assign it to `NODE_CLASS`; category `__init__.py` files must not eagerly import nodes.
4. Define metadata as class variables (do not duplicate Node DSL metadata in `node.yaml`):
```python
TITLE: ClassVar[str] = "My Node Title"
CATEGORY: ClassVar[str] = "Data Sources"
TAGS: ClassVar[List[str]] = ["database", "postgres"]
TYPE: ClassVar[enums.NodeType] = enums.NodeType.BASE
DESCRIPTION: ClassVar[str] = "Node description"
```
4. Define fields using `InputField` and `OutputField` with type annotations
5. Implement `process()` method (abstract, required)
6. Run `{venv_dir_path}/Scripts/python.exe -m scripts.update_locales` to update i18n

### gRPC Communication

**Store Service**: Uses gRPC for content and index storage. Create clients via:
```python
from src.clients.store_client import GrpcStoreClient
from src.clients.index_store_client import GrpcIndexStoreClient
```

**Log Forwarding**: Task Worker forwards logs to Gateway via gRPC (WSForwardClient → ForwardWSServicer → WebSocket).

**Channel Options**: Use `src.runtime.grpc_channel.default_channel_options()` for proper service reflection configuration.

### Logging System

Multi-sink logging architecture (configured in `logging.yaml`):
- **Console sink**: Standard output
- **DB sink**: Logs to database (enabled via `LOG_TO_DB=true`)
- **WebSocket sink**: Real-time logs to UI (enabled via `LOG_TO_WS=true`)

Logs from Task Worker are forwarded to Gateway via gRPC, then broadcasted to connected WebSocket clients.

### Pipeline Execution Flow

1. User triggers pipeline via Gateway API
2. Gateway validates pipeline and creates task
3. Task published to Kafka topic
4. Task Worker consumes task
5. Task Worker executes nodes sequentially, caching DataFrame partitions
6. Progress/logs sent to Gateway via gRPC
7. Gateway broadcasts updates to UI via WebSocket

## Configuration

Configuration is centralized in `config.py` (loaded from environment variables or `.env`):

**Database**:
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`

**Services**:
- `GATEWAY_HOST`, `GATEWAY_PORT`
- `TASK_WORKER_HOST`, `TASK_WORKER_PORT`
- `TASK_SCHEDULER_HOST`, `TASK_SCHEDULER_PORT`
- `GRPC_FORWARD_SERVICE_HOST`, `GRPC_FORWARD_SERVICE_PORT`, `GRPC_FORWARD_SERVICE_TOKEN`

**Kafka**:
- `KAFKA_BROKER` (e.g., `redpanda:29092` in Docker, `localhost:9092` on host)

**S3** (optional):
- `S3_ENABLED`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_ENDPOINT_URL`, `S3_USER_FILES_BUCKET`

**Logging**:
- `LOG_LEVEL`, `LOG_TO_DB`, `LOG_TO_WS`
- `LOGS_CLEANUP_CRON`, `LOGS_CLEANUP_TRESHOLD_DAYS`, `LOGS_CLEANUP_BATCH_SIZE`

**Security**: Never commit secrets. Use `.env` file (gitignored) or environment variables.

## Git Workflow

Current branch: `dev-ayupov`

### Commit Message Format

Use prefixes:
- `ADD` - New feature/functionality
- `UPD` - Enhancement to existing feature
- `FIX` - Bug fix
- `CLR` - Cleanup/refactoring

Example: `FIX encrypted connection passwords on task_worker`

### Agent-Specific Files

**AGENTS.md**: Project description, guidelines, and standards for AI agents
**AGENTS_TASKS.md**: List of pending tasks (agent executes only on explicit user request)
**AGENTS_CHANGELOGS.md**: Log of all agent modifications (entries in Russian, format: `### YYYY-MM-DD HH:MM:SS`)
**AGENTS_TIPS.md**: Agent knowledge base for documenting solutions to complex problems
**src/utils/agents_tools.py**: Custom helper functions created by agent (must have docstrings and be documented in AGENTS_TIPS.md)

**Important**: When making changes, update `AGENTS_CHANGELOGS.md` with Russian-language entry.

## Common Operations

### Update Localization
```bash
{venv_dir_path}/Scripts/python.exe -m scripts.update_locales
```

### Health Checks
```bash
# Gateway health
curl http://localhost:8001/api/health

# Check via script (used in Docker healthcheck)
{venv_dir_path}/Scripts/python.exe scripts/health/check_gateway_health.py
```

### Access Redpanda Console
http://localhost:8080 - Monitor Kafka topics, messages, consumer groups

### Run Project via API

Get API key from `{DVT_URL}/api-keys`, then:
```bash
# Start project
curl -X POST "{DVT_URL}/api/public/projects/{PROJECT_ID}/tasks/new?mode=full" \
  -H "X-API-KEY: {API_KEY}"

# Check task status
curl -X GET "{DVT_URL}/api/public/projects/{PROJECT_ID}/tasks/{TASK_ID}/info" \
  -H "X-API-KEY: {API_KEY}"

# Cancel task
curl -X POST "{DVT_URL}/api/public/projects/{PROJECT_ID}/tasks/{TASK_ID}/cancel" \
  -H "X-API-KEY: {API_KEY}"
```

See `docs/RUN_PROJECTS.md` for Python/PowerShell/Airflow examples.

## Important Notes

- **Windows Environment**: Project runs on Windows (Git Bash recommended for scripts)
- **Docker Networking**: Services communicate via service names in Docker (e.g., `redpanda:29092`), use `localhost` ports from host
- **Service Tokens**: gRPC services use token-based authentication (Store, Forward services)
- **Log Cleanup**: Automated via APScheduler job in Gateway (uses PostgreSQL advisory locks for single-instance execution)
- **Node Caching**: `DFOutputBaseNode` automatically caches each partition of output DataFrames to Store service
- **Metadata**: Nodes can provide metadata via `MetadataNodeMixin` for downstream consumption
