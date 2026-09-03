# DVT (Denvic Visual Transformer)

Визуальный ETL-инструмент для построения, запуска и мониторинга data pipeline через
node-based интерфейс.

## Описание проекта

DVT состоит из нескольких backend-сервисов и общего Python-ядра в `src/`. Пользователь
проектирует граф из узлов в UI, Gateway сохраняет его в PostgreSQL, а затем запускает
исполнение через Orchestrator и Task Worker. Выполнение задач идет асинхронно через
Celery + Valkey, статусы и события пробрасываются обратно в UI по WebSocket.

### Основные возможности

- Визуальный редактор pipeline на основе узлов
- Распределенное выполнение задач через Celery workers
- Node DSL для расширения набора ETL-узлов
- Кэширование данных и метаданных между узлами
- Планировщик запуска проектов по cron
- Real-time мониторинг выполнения через WebSocket
- REST API и OpenAPI для управления проектами
- Расширения (`extensions/`) и инфраструктурные интеграции

## Текущая архитектура

### Сервисы

- **Gateway** (`services/gateway/`) — основной FastAPI API gateway. Отвечает за auth,
  проекты, граф, запуск задач, OpenAPI и WebSocket.
- **Orchestrator** (`services/orchestrator/`) — gRPC сервис оркестрации. Принимает
  внутренние задачи от Gateway, отслеживает heartbeat/telemetry воркеров и назначает
  задания в Celery queue.
- **Task Worker** (`services/task_worker/`) — Celery worker, который исполняет pipeline
  и публикует execution events, heartbeat и telemetry.
- **Project Scheduler** (`services/project_scheduler/`) — отдельный сервис cron-планировщика
  для регулярного запуска проектов.
- **UI** (`services/ui/`) — Vite frontend с визуальным редактором узлов.
- **Proxy** (`services/proxy/`) — Nginx reverse proxy для выдачи UI и проксирования API.
- **Task Benchmarking** (`services/task_benchmarking/`) — benchmarking pipeline по времени
  и памяти.
- **Tester** (`services/tester/`) — CI helper образ для запуска тестов.

### Инфраструктура

- **PostgreSQL** — основная БД для проектов, графов, задач, расписаний и системных данных
- **Valkey** — Celery broker/result backend, Pub/Sub канал heartbeat и stream событий выполнения
- **Celery** — доставка задач от Orchestrator к Task Worker
- **gRPC** — межсервисное взаимодействие Gateway, Orchestrator и WS-forward каналов
- **WebSocket** — real-time доставка статусов и событий в UI
- **APScheduler** — cron-планирование запуска проектов

### Архитектурный поток выполнения

1. Пользователь изменяет граф проекта или запускает задачу через Gateway API.
2. Gateway читает `GraphNode` / `GraphEdge` из PostgreSQL и собирает исполняемый `Pipeline`.
3. Gateway формирует внутреннюю задачу и отправляет ее в Orchestrator по gRPC.
4. Orchestrator ставит задачу в pending queue и выбирает живой worker по heartbeat/telemetry.
5. Назначение задачи происходит через Celery очередь в Valkey.
6. Task Worker выполняет pipeline через `src.pipeline`, используя `src.node_dsl`,
   `src.nodes`, `src.caching`, `src.runtime` и другие общие модули.
7. Worker публикует heartbeat, execution events и telemetry через Valkey Pub/Sub и Stream.
8. Orchestrator обновляет статусы/метаданные и пересылает события в Gateway через WS-forward.
9. Gateway транслирует обновления в UI по WebSocket.

## Структура репозитория

```text
src/
├── node_dsl/         # Фреймворк для определения ETL-узлов
├── nodes/            # Реализации ETL-узлов
├── pipeline/         # Построение, валидация и выполнение pipeline
├── clients/          # Gateway / Orchestrator / Scheduler / WS-forward / external clients
├── crud/             # Операции чтения/записи в PostgreSQL
├── models/           # SQLModel модели домена и БД
├── schemas/          # Pydantic схемы HTTP / gRPC / event payloads
├── dto/              # DTO между слоями и сервисами
├── db/               # Настройка подключения к БД
├── caching/          # Кэширование промежуточных данных и индексов
├── infra/            # Infrastructure/use-case helpers вокруг задач и выполнения
├── managers/         # Сервисные менеджеры и orchestration helpers
├── runtime/          # Runtime утилиты и инфраструктурные каналы
├── extensions/       # Runtime расширений
├── logger/           # Логирование в stdout / БД / WebSocket
└── utils/            # Вспомогательные функции

core/                 # Общие низкоуровневые инфраструктурные примитивы
contracts/            # gRPC/protobuf контракты и сгенерированный код
migrations/           # Alembic миграции
scripts/              # Скрипты запуска сервисов, Docker и утилиты
services/             # Deployable сервисы и entrypoints
tests/                # Unit / integration / e2e тесты
docker/               # Compose-файлы для dev/test окружений
.codex/skills/         # Project skills для локальной разработки и диагностики
```

## Node DSL

Проект использует собственный DSL для описания ETL-узлов:

- `BaseNode` — базовый класс узла
- `InputField` / `OutputField` — декларативное описание входов и выходов
- автоматическая регистрация узлов через registry
- lifecycle выполнения через `execute()` / hooks / `process()`
- типизированные категории узлов: источники, трансформации, назначения, системные узлы

## Требования

- Python 3.13
- Docker и Docker Compose
- Node.js 16+ для UI-сценариев
- PostgreSQL и Valkey (обычно поднимаются через Docker)

## Установка и окружение

### Canonical repository и UI submodule

Canonical Source of Truth для Backend — GitHub repository `Denvic-Tech/dvt`. Внутренние GitLab repositories являются CI/CD-инфраструктурой и зеркалами; доступ к ним для разработки и contribution не требуется.

Frontend подключён как pinned Git submodule `services/ui` из canonical GitHub repository `Denvic-Tech/dvt-ui`. Обычная инициализация использует зафиксированный Backend gitlink SHA:

```bash
git submodule update --init --recursive
```

Чтобы явно обновить локальный UI до актуального состояния его configured branch и смержить обновление в submodule worktree, используйте существующий developer workflow:

```bash
git submodule update --remote --merge services/ui
```

После этого новый UI gitlink нужно закоммитить вместе с Backend-изменением; release/build CI никогда не делает `--remote` и не подменяет pinned UI revision на `latest`.

### 1. Клонирование

```bash
git clone --recurse-submodules https://github.com/Denvic-Tech/dvt.git
cd DVT
```

### 2. Виртуальное окружение

```bash
python3.13 -m venv .venv

# Git Bash
source .venv/Scripts/activate

# PowerShell
.\.venv\Scripts\Activate.ps1
```

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 4. Минимальные переменные окружения

Локальные defaults уже зашиты в `config.py`, но обычно достаточно явно задать:

```bash
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=15433
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=DVT

VALKEY_HOST=127.0.0.1
VALKEY_PORT=16379
VALKEY_PASSWORD=valkeypass
VALKEY_DB=0

GATEWAY_HOST=127.0.0.1
GATEWAY_PORT=8200

ORCHESTRATOR_HOST=127.0.0.1
ORCHESTRATOR_PORT=8250

PROJECT_SCHEDULER_HOST=127.0.0.1
PROJECT_SCHEDULER_PORT=8201

GRPC_FORWARD_SERVICE_HOST=127.0.0.1
GRPC_FORWARD_SERVICE_PORT=45061
GRPC_FORWARD_SERVICE_TOKEN=secret-token-WS-FORWARD
```

`CELERY_BROKER_URL` и `CELERY_RESULT_BACKEND` по умолчанию собираются из `VALKEY_*`.
`CELERY_VISIBILITY_TIMEOUT_SEC` задаёт время ожидания подтверждения Celery-задачи и по
умолчанию равен `28800` секунд (8 часов). В Docker Compose параметр переопределяется через
`DVT_CELERY_VISIBILITY_TIMEOUT_SEC`. Значение должно с запасом превышать максимальную
длительность ETL-задачи. При жёстком падении worker большое значение может на это же время
задержать возврат неподтверждённой задачи в очередь.

Пользовательский AI MCP-сервис является опциональным и по умолчанию выключен:

```bash
DVT_AI_MCP_ENABLED=false
```

Для включения через `install.sh` используйте `--enable-ai-mcp`; при прямом запуске Compose
дополнительно активируйте профиль `ai-mcp`. Включённому сервису требуется уникальный
`DVT_AI_MCP_INTERNAL_SECRET` длиной не менее 32 символов. Installer генерирует отсутствующий
секрет автоматически. При выключении Gateway не публикует MCP API, proxy отвечает `404` на
`/mcp`, а контейнер `dvt-ai-mcp` не запускается.

Production installer также генерирует отдельные JWT secrets и code hash salt для Gateway.
Требования к ним и порядок безопасной ротации описаны в
[`docs/security/jwt-secret-rotation.md`](docs/security/jwt-secret-rotation.md).

## Локальный запуск backend (без полного Docker-стека)

### 1. Поднять инфраструктуру

```bash
docker compose --project-directory . \
  -f docker/docker-compose.base.yaml \
  -f docker/docker-compose.dev.yaml \
  up -d postgres valkey
```

### 2. Применить миграции

```bash
<venv_dir>/Scripts/python.exe -m alembic upgrade head
```

### 3. Запустить сервисы

Откройте несколько терминалов и запустите:

```bash
# Gateway
<venv_dir>/Scripts/python.exe -m scripts.services.run_gateway

# Orchestrator
<venv_dir>/Scripts/python.exe -m scripts.services.run_orchestrator

# Task Worker
<venv_dir>/Scripts/python.exe -m scripts.services.run_task_worker

# Project Scheduler
<venv_dir>/Scripts/python.exe -m scripts.services.run_project_scheduler
```

### 4. Локальные адреса

- Gateway API: `http://localhost:8200/api/docs`
- Project Scheduler API: `http://localhost:8201/docs`

### Масштабирование Task Worker

- Параллелизм управляется через `CELERY_WORKER_CONCURRENCY` и `TASK_WORKER_MAX_CONCURRENT`
- Имя очереди выполнения задаётся через `CELERY_TASKS_QUEUE`; STOP хранится в lifecycle PostgreSQL.
- В Docker можно поднять несколько воркеров:

```bash
docker compose --project-directory . \
  -f docker/docker-compose.base.yaml \
  -f docker/docker-compose.dev.yaml \
  up --scale task-worker=3 task-worker
```

## Release Docker images

Официальные release-образы собираются в CI через Docker Buildx Bake ровно один раз под pipeline-specific candidate tag. После push CI фиксирует digest каждого candidate image; integration tests загружают backend candidates по immutable `@sha256` refs, а promotion использует сохранённые протестированные digest'ы, а не изменяемый candidate tag. После тестов те же remote manifests без пересборки получают version tag, а stable release дополнительно получает `latest`. Compose-файлы остаются источником build definitions, а `docker/docker-bake.release.hcl` задаёт release group, registry и candidate tagging policy для `cr.distribution.denvic.tech/dvt/*`.

Локальная production-like сборка через Compose по-прежнему поддерживает `UI_BUILD_CONTEXT`, поэтому UI можно собирать из отдельного checkout с незапушенными изменениями. Официальный candidate Bake всегда принудительно использует pinned Git submodule `services/ui` и `VITE_API_BASE_URL=/api`.

## Запуск в Docker

### Полный dev-стек

```bash
docker compose --project-directory . \
  -f docker/docker-compose.base.yaml \
  -f docker/docker-compose.dev.yaml \
  up --build
```

Фоновый запуск:

```bash
docker compose --project-directory . \
  -f docker/docker-compose.base.yaml \
  -f docker/docker-compose.dev.yaml \
  up -d --build
```

Логи:

```bash
docker compose --project-directory . \
  -f docker/docker-compose.base.yaml \
  -f docker/docker-compose.dev.yaml \
  logs -f
```

Остановка:

```bash
docker compose --project-directory . \
  -f docker/docker-compose.base.yaml \
  -f docker/docker-compose.dev.yaml \
  down
```

### Доступные endpoints в Docker dev

- UI: `http://localhost:81`
- Gateway API: `http://localhost:8001/api/docs`
- Project Scheduler API: `http://localhost:8002/docs`
- Proxy: `http://localhost:80`

### Поднять только часть стека

```bash
docker compose --project-directory . \
  -f docker/docker-compose.base.yaml \
  -f docker/docker-compose.dev.yaml \
  up gateway orchestrator task-worker
```

## Работа с БД

### Миграции

```bash
# Применить миграции
<venv_dir>/Scripts/python.exe -m alembic upgrade head

# Создать новую миграцию
alembic revision --autogenerate -m "Add new table"
```

## Тестирование

### Локальный запуск

```bash
# Все тесты
<venv_dir>/Scripts/python.exe -m pytest

# Только unit
<venv_dir>/Scripts/python.exe -m pytest tests/unit

# Только integration
<venv_dir>/Scripts/python.exe -m pytest tests/integration

# По ключевому слову
<venv_dir>/Scripts/python.exe -m pytest -k "test_node_execution"
```

### Dockerized тесты

```bash
docker compose --project-directory . \
  -f docker/docker-compose.base.yaml \
  -f docker/docker-compose.dev.yaml \
  -f docker/docker-compose.tests.yaml \
  --profile testing up tester_unit
```

Или через проектные скрипты:

```bash
<venv_dir>/Scripts/python.exe scripts/docker/unit_tests.py
<venv_dir>/Scripts/python.exe scripts/docker/integration_tests.py
<venv_dir>/Scripts/python.exe scripts/docker/e2e_tests.py
```

### Benchmarking

Перед экспериментами прочитайте `services/task_benchmarking/README.md`.

## Создание новых узлов

1. Создайте модуль узла в соответствующей категории внутри `src/nodes/`.
2. Унаследуйтесь от подходящего базового класса (`DFOutputBaseNode`, `SqlConnectionOutputBaseNode`
   и т.д.).
3. Опишите метаданные узла (`TITLE`, `CATEGORY`, `DESCRIPTION`, `TYPE`, `TAGS`).
4. Объявите поля через `InputField` и `OutputField`.
5. Реализуйте `process()`.
6. Обновите локализацию и проверьте регистрацию узла.

## Troubleshooting

### Проблемы с PostgreSQL

- Проверьте, что контейнер БД запущен:

```bash
docker compose --project-directory . \
  -f docker/docker-compose.base.yaml \
  -f docker/docker-compose.dev.yaml \
  ps postgres
```

- Проверьте `POSTGRES_*` в `.env`
- Локально defaults используют порт `15433`, а не `5432`

### Проблемы с Valkey / Celery

- Проверьте, что `valkey` запущен и отвечает на `PING`
- Проверьте `VALKEY_HOST`, `VALKEY_PORT`, `VALKEY_PASSWORD`, `VALKEY_DB`
- Если задачи не назначаются, проверьте:
  - запущен ли `orchestrator`
  - запущен ли `task_worker`
  - публикуются ли heartbeat/event сообщения
  - совпадает ли `CELERY_TASKS_QUEUE` у orchestrator и worker

### Ошибки миграций

```bash
alembic current
alembic history
alembic downgrade -1
```

### Очистка Docker volumes

```bash
docker compose --project-directory . \
  -f docker/docker-compose.base.yaml \
  -f docker/docker-compose.dev.yaml \
  down -v
```

## Дополнительные материалы

- `AGENTS.md` — инструкции для coding agents и описание сервисов
- `services/task_benchmarking/README.md` — benchmarking workflow
- `docs/` — дополнительная документация
- `contracts/` — gRPC/protobuf контракты

## Поддержка

Если поведение README расходится с фактическим кодом или compose-конфигурацией, ориентируйтесь
на `services/*`, `scripts/services/*`, `docker/docker-compose.*.yaml` и `AGENTS.md`: они отражают
текущее состояние системы точнее, чем устаревшие заметки в старых разделах документации.
