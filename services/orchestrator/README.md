# DVT Task Orchestrator (Celery + gRPC)

`services/orchestrator` — сервис распределения задач между воркерами, адаптированный под
`task_worker`. Он принимает задания по gRPC, держит локальную очередь pending-задач,
отслеживает состояние воркеров по Valkey heartbeat и назначает задачи через Celery.
Также обрабатывает события воркеров из Valkey Stream и пересылает их в gateway (WS) и БД.

## Основные функции

- Прием задач через gRPC `EnqueueTask`.
- Назначение задач через Celery очередь `CELERY_TASKS_QUEUE`.
- Отслеживание heartbeat воркеров через Valkey Pub/Sub (`CELERY_HEARTBEAT_CHANNEL`).
- Обработка событий воркеров из Valkey Stream (`ORCH_EVENTS_STREAM`).
- gRPC методы для отмены задач и получения system stats.

## Архитектура и компоненты

- `main.py` — gRPC сервер и запуск фоновых слушателей Valkey.
- `servicers/orchestrator.py` — gRPC обработчики методов.
- `scheduler.py` — планировщик, распределяющий pending-задачи.
- `worker_registry.py` — in-memory реестр воркеров (busy/alive/capabilities).
- `redis_listeners.py` — слушатели heartbeat и stream событий.
- `deps/worker_event_callbacks.py` — обработчики событий воркеров (DB + WS).

## gRPC API

Контракты находятся в `contracts/protos/orchestrator/v1/orchestrator.proto`.

- `EnqueueTask` — прием задачи (JSON `TaskInternal`).
- `CancelTask` — отмена задачи.
- `GetSystemStats` — системная информация от живых воркеров.

## Valkey события воркеров

События поступают в `ORCH_EVENTS_STREAM` и содержат сериализованный `WorkerEventPayload`
из `src/schemas/worker_event_payload.py`. Воркеры отправляют следующие типы:
- `TaskExecutionStatusEvent`
- `NodeExecutionStatusEvent`
- `NodeMetadataEvent`

Обработчики обновляют статусы задач в БД и отправляют WS сообщения в gateway.

## Celery/Valkey настройки

| Переменная окружения | Значение по умолчанию | Назначение |
|---|---|---|
| `CELERY_BROKER_URL` | `redis://...` | URL брокера Celery. |
| `CELERY_VISIBILITY_TIMEOUT_SEC` | `28800` | Время до повторной доставки неподтверждённой задачи; должно превышать максимальную длительность задачи. |
| `CELERY_TASKS_QUEUE` | `tasks.worker` | Очередь для задач выполнения. |
| `CELERY_HEARTBEAT_CHANNEL` | `workers.heartbeat` | Канал heartbeat воркеров. |
| `ORCH_EVENTS_STREAM` | `orchestrator.events` | Valkey Stream событий воркеров. |
| `ORCH_EVENTS_GROUP` | `orchestrator-events` | Consumer group для стрима. |
| `ORCH_EVENTS_CONSUMER` | `<service instance>` | Consumer name. |

Большое значение visibility timeout защищает долгие задачи от дублирования, но может задержать
redelivery после жёсткого падения worker на время до указанного timeout.

## Локальный запуск

```powershell
{venv_dir_path}\Scripts\python.exe -m services.orchestrator.main
```

## Docker

В директории сервиса есть Dockerfiles:

- `services/orchestrator/docker/dev.Dockerfile`
- `services/orchestrator/docker/prod.Dockerfile`

Оба запускают gRPC сервер и используют переменные
`ORCHESTRATOR_HOST` / `ORCHESTRATOR_PORT`.

## Связанные сервисы

- `services/task_worker` — выполняет задачи, отправляет heartbeat и события.
- `services/gateway` — вызывает gRPC методы orchestrator для постановки/отмены задач и stats.
