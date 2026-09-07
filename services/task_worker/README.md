# Task Worker

## Назначение
`task_worker` выполняет ETL-задачи пайплайна. Задачи приходят через Celery + Valkey, а STOP
наблюдается по authoritative marker PostgreSQL. HTTP API больше не используется — сервис работает как фоновой исполнитель
и отправляет heartbeat и события.

Сервис запускается одним Celery воркером с одним execution slot. В production/Linux используется
`prefork`: MainProcess один раз прогревает built-in/extension runtime, а каждый Celery task выполняется
в отдельном child-процессе, который после задачи завершается. Это оставляет task-scoped cleanup основным
логическим cleanup-механизмом, но дополнительно гарантирует возврат ОС памяти, файловых дескрипторов и
состояния native-библиотек между pipeline execution.

На native Windows для локальной разработки по умолчанию используется `solo`, поскольку Celery prefork
на Windows работает через `spawn` и не является поддерживаемым production-equivalent режимом. В `solo`
нет отдельного execution child, поэтому process isolation и принудительный `HARD_STOP` выполняемой задачи
не эквивалентны production. Для проверки recycling/HARD_STOP следует запускать Task Worker в Docker/Linux.

## Взаимодействие с другими сервисами
- Gateway (`services/gateway`):
  - Используется `GatewayClient` для взаимодействия с gateway API.
  - Логи могут пересылаться в WebSocket через gRPC forward.
- Orchestrator/Scheduler:
  - Должны отправлять задания в Celery очередь `CELERY_TASKS_QUEUE`.
  - Orchestrator сохраняет STOP в lifecycle задачи; worker наблюдает marker и останавливается cooperative.
  - Heartbeat публикуется в Valkey канал `CELERY_HEARTBEAT_CHANNEL`.
- Store/Index Store:
  - Используются gRPC клиенты из `services/task_worker/helpers` и `services/task_worker/deps`.
- PostgreSQL:
  - Authoritative lifecycle читается/изменяется через `src/modules/task_execution`.
- Valkey:
  - Используется как брокер Celery и как канал для heartbeat.
- gRPC WS forward:
  - Используется для логирования в WebSocket (если `LOG_TO_WS=true`).

## Поток обработки задач
1) Производитель кладет задание в очередь `CELERY_TASKS_QUEUE`.
2) Celery worker получает задание `task_worker.handle_task`.
3) Статус задачи меняется на STARTED в БД.
4) В Linux/prefork задание выполняется в отдельном Celery worker child-процессе.
5) После завершения Celery task child завершается (`max_tasks_per_child=1`), а MainProcess создаёт свежий
   child из уже прогретого runtime для следующей задачи.
6) Прогресс и статус отправляются через WS forward (если разрешено), а результат фиксируется в БД.

Built-in ноды и актуальные extensions загружаются в prefork MainProcess до создания pool, поэтому обычная
смена child не требует полного импорта всех нод перед каждой задачей. Если child замечает новую generation
расширений, он обновляет runtime для текущей задачи и просит MainProcess безопасно обновить warm template:
приём task/deps очередей приостанавливается, текущая работа дренируется, pool временно уменьшается до `0`,
parent обновляет registries, после чего единственный execution slot восстанавливается и очереди возобновляются.

STOP не проходит через очередь Celery: после текущей node worker видит `CANCEL_REQUESTED` и не запускает следующую.

## Heartbeat
Celery worker регулярно публикует heartbeat в Valkey канал `CELERY_HEARTBEAT_CHANNEL`.
Формат payload соответствует `src/modules/task_execution/infra/transport/worker_heartbeat.py` и сериализуется в JSON.

## Конфигурация
Основные переменные окружения (см. `config.py`/`config_prod.py`):
- `VALKEY_HOST`, `VALKEY_PORT`, `VALKEY_PASSWORD`, `VALKEY_DB`.
- `CELERY_BROKER_URL` - URL брокера Valkey.
- `CELERY_RESULT_BACKEND` - backend Celery (по умолчанию равен брокеру).
- `CELERY_VISIBILITY_TIMEOUT_SEC` - время ожидания подтверждения задачи до повторной доставки;
  по умолчанию `28800` секунд (8 часов), должно превышать максимальную длительность задачи.
- `CELERY_TASKS_QUEUE` - очередь для задач выполнения.
- `CELERY_HEARTBEAT_CHANNEL` - Valkey канал для heartbeat.
- `CELERY_WORKER_CONCURRENCY` - конкуррентность воркера; для Task Worker обязана быть `1`.
- `CELERY_WORKER_POOL` - execution pool; default `prefork` на Linux и `solo` на native Windows.
- `CELERY_WORKER_MAX_TASKS_PER_CHILD` - для `prefork` default `1`: execution child перерабатывается после
  каждой Celery task. Значение можно увеличить как осознанный performance/isolation trade-off.
- `CELERY_WORKER_MAX_MEMORY_PER_CHILD` - дополнительный memory-based safety net для prefork.
- `CELERY_WORKER_PREFETCH_MULTIPLIER`, `CELERY_TASK_ACKS_LATE`, `CELERY_TASK_REJECT_ON_WORKER_LOST`.

Увеличение `CELERY_VISIBILITY_TIMEOUT_SEC` предотвращает повторную доставку долгих задач,
но при жёстком падении worker может на это же время задержать их возврат в очередь.

Также используются общие настройки:
- `TASK_WORKER_MAX_CONCURRENT`, `TASK_WORKER_HEARTBEAT_INTERVAL`.
- `LOG_LEVEL`, `LOG_TO_WS`, `LOG_TO_DB`, `GATEWAY_URL`.
- `POSTGRES_*`, `STORE_*`, `INDEX_STORE_*`, `GRPC_FORWARD_*`.

## Запуск
Один процесс Celery воркера:
```
{venv_dir_path}\Scripts\python.exe -m services.task_worker.main
```

Эквивалентная команда:
```
{venv_dir_path}\Scripts\python.exe -m celery -A services.task_worker.celery_app worker -Q tasks.worker,tasks.deps
```

## Чем отличается от старого `task_worker`
- Вместо Kafka/Redpanda используется Celery + Valkey.
- Heartbeat публикуется в Valkey канал `CELERY_HEARTBEAT_CHANNEL`, а не в Kafka топик.
- Обработка задач вынесена в Celery task `task_worker.handle_task`.
- Не используется FastStream/Kafka Router; HTTP API удален.

## Формат сообщений
Задание (`task_worker.handle_task`) принимает JSON, совместимый со схемой
`src/schemas/internal/task.py::TaskInternal`.
