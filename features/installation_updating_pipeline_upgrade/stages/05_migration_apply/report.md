# Отчёт об этапе 05: мигратор, полный Compose и готовность

- **Статус:** `READY_FOR_REVIEW`.
- **Задание:** [task.md](./task.md).
- **Режим:** `IMPLEMENT`. База: `d542556`.

## 1. Что сделано

- Production и dev запускают `migrate` как одноразовый сервис из образа Gateway после
  готовности PostgreSQL. Четыре роли, которые используют БД, ждут его успешного завершения
  и проверяют ожидаемую схему при старте. HTTP Gateway не меняет схему.
- В проверенном пути мигратор держит advisory lock до конца подготовки расширений. Core
  и запись `core` фиксируются в одной транзакции; `done` записывается после подтверждения
  обязательных расширений. Повтор по тому же ID проверяет существующий результат в текущей
  PostgreSQL (идентификатор кластера и OID базы), ревизию, подписанный комплект и digest
  Gateway. Подтверждённую миграцию и подготовку расширений повторно не выполняет.
- Исполнитель повторно проверяет подписанный комплект, разрешённый маршрут, модель Compose
  и, для UPDATE, сохранённую копию и замороженный gate. Запуск приложения использует полный
  `compose up` без списка прикладных ролей. Проверки охватывают Gateway и UI по
  пользовательскому адресу Proxy, Scheduler, Orchestrator, текущие контейнеры и локальный
  heartbeat воркеров, а также контракт Gateway ↔ MCP и публичный маршрут при включении.
- Замена мастера сверяет формат журнала и доступ к тому же ID; при недоступном целевом
  мастере восстанавливается предыдущий digest. После готовности сохраняются рабочие
  `.env` и `docker-compose.yaml`, затем атомарно публикуется указатель комплекта. Gate
  открывается только по своему ID, с транзакционной записью `resumed`. Лишь после её проверки
  журнал получает `SUCCEEDED`.
- Истечение срока подписи не препятствует доведению того же ранее разрешённого комплекта,
  если подтверждены `done`/`resumed` и фактическая ревизия. Новая или неподтверждённая
  миграция требует действующей подписи. Отзыв ключа и удаление корня блокируют и продолжение.

## 2. Изменённые файлы

| Путь (от корня) | Изменение |
| --- | --- |
| `docker-compose.yaml`, `docker/docker-compose.dev.yaml`, `docker/docker-compose.prod.override.yaml` | Барьер PostgreSQL → migrate → прикладные роли, независимость мастера, dev и local prod build из одного определения Gateway. |
| `services/gateway/{migrate.py,main.py,lifespan.py,deployment_probe.py,docker/*.Dockerfile,update_runtime/middleware.py}`, `migrations/env.py`, `src/utils/{deployment_migrations,waiting}.py` | Standalone миграции и доказательство БД, SQLAlchemy соединение Alembic под advisory lock, проверки схемы при старте, живые проверки Gateway и Orchestrator. |
| `services/installation_manager/{candidate_executor,candidate_main}.py`, `application/{application_apply,verified_staging}.py`, `infrastructure/{application_host,maintenance_host,release_verification,staging_compose}.py`, `domain/release_manifest.py` | Исполнитель переключения, верификация сохранённых артефактов, подтверждение readiness и resume, совместимое поле обязательных расширений. |
| `services/project_scheduler/main.py`, `services/dvt_ai_mcp/{gateway_client,server}.py` | Готовность Scheduler и MCP; у MCP проверяется приватная авторизация на Gateway без пользовательского токена. |
| `tests/integration/services/gateway/test_migration_receipt.py`, `tests/unit/services/installation_manager/application/test_application_apply.py`, `tests/unit/services/dvt_ai_mcp/test_gateway_readiness.py`, `tests/unit/services/gateway/update_runtime/test_middleware.py` | Проверки отказов PostgreSQL, повторного применения, fallback мастера, профиля MCP и маршрутов готовности. |
| `services/installation_manager/migration_apply.md`, `AGENTS_CHANGELOGS.md`, текущий отчёт и fixture | Контракт эксплуатации, журнал и очищенное доказательство. |

## 3. Критерии приёмки

| Критерий | Статус | Подтверждение |
| --- | --- | --- |
| `SAC-01` | `PASS` | Реальная история Alembic на чистой PostgreSQL, завершаемый guarded переход `0070 → 0070` для релиза без смены схемы, откат транзакции при инъекции сбоя. На Debian и Ubuntu настоящий Compose оставил синтетические зависимые роли остановленными при отказе мигратора; мастер продолжал работать. |
| `SAC-02` | `PASS` | Реальная блокировка конкурирующего мигратора; отказ при конфликте операции или OID БД; отсутствие обязательного расширения оставляет `core`; после готовности расширения повтор даёт `done` и второй успех не повторяет подготовку. |
| `SAC-03` | `PASS` | На Debian и Ubuntu поздний Gateway потребовал повторного полного `up` при обоих профилях; fixture записал core один раз. Тест приложения удерживает указатель до readiness, требует подтверждения resume и не повторяет миграцию. Отдельно проверен fallback на прежний digest мастера. |

Оценка относится к изолированным проверкам этапа. Полный релизный стек с продуктовыми образами
на хосте здесь не поднимался.

## 4. Проверки

| Команда или сценарий | Результат | Детали |
| --- | --- | --- |
| `<venv> -m pytest tests/unit/services/gateway/test_migrate_import.py tests/unit/services/installation_manager tests/unit/src/utils/test_waiting.py tests/unit/services/dvt_ai_mcp tests/unit/services/gateway/update_runtime -p no:cacheprovider --tb=short` | `PASS` | 119 прошли; 7 пропущены (Linux-only и отсутствующий пакет MCP для отдельного smoke-модуля). Новые MCP HTTP-проверки прошли. |
| `<venv> -m pytest tests/integration/services/gateway/test_migration_receipt.py -p no:cacheprovider --tb=short` | `PASS` | Оба теста прошли локально с отдельными контейнерами PostgreSQL 15.3 и повторены мастер-агентом. Первый запуск выявил неполную синтетическую строку расширения, исправленную до успешного повтора. |
| `bash artifacts/compose_fault_fixture.sh` | `PASS` | Независимые прогоны мастер-агента на Debian 13 и Ubuntu 24.04: при MCP off и on зафиксированы отказ, здоровый мастер, поздний Gateway и успешный повтор, один синтетический core write. Реальная PostgreSQL; приложение моделируется. |
| `docker compose ... config --quiet` / `--format json` | `PASS` | Root без MCP и с MCP, base + dev, base + dev + testing, base + dev + prod override; проверены одинаковый образ, зависимости и независимость мастера. Проверен локальный Compose с отдельной сетью кандидата. |
| `docker buildx bake ... release --print` | `PASS` | Сверены точные файлы CI. Группа релиза содержит один prod Gateway и не добавляет отдельный артефакт migrate. Не выполнялись build, push и promote. |
| Ruff и `git diff --check --ignore-submodules` | `PASS` | Нет новых диагностик; общий Ruff по изменённым Python-файлам показывает шесть исходных замечаний в неизменённых строках Scheduler и `waiting.py`. |
| Продуктовая установка/обновление с опубликованным манифестом, реальными готовыми образами, браузером и ETL | `NOT_RUN` | Полноценная матрица этапа 10; beta и действующие установки не запускались. Здесь смена ревизии проверена на полной чистой истории; guarded переход проверен на релизе без смены уже имеющей guard ревизии. |
| Legacy без guard, возврат к старому комплекту, полное восстановление на другой ВМ | `NOT_RUN` | Вне объёма этапа 05. |

## 5. Ограничения

- Для проверенного обновления поддерживается частный PostgreSQL с защищённым постоянным
  bind mount, без смены инфраструктурного digest. Копия источника сделана до записи
  результата миграции; логическое восстановление этой копии не приносит новую запись.
  Физическое клонирование с сохранением идентификаторов PostgreSQL не проверялось.
- Нужен достижимый из host network пользовательский origin приложения с действительной TLS
  цепочкой при HTTPS. Bootstrap-адрес мастера не подходит как публичный адрес приложения.
- Отзыв между staging и apply учитывается, когда актуальная политика передана хозяином
  экземпляра в защищённом `.bootstrap/release-trust.json`. Автоматической доставки политики
  каталога на этом этапе нет.
- Compose shell fixture не подменяет готовность настоящих DVT образов. Истечение срока
  до подтверждённого `done`, отзыв и потеря корректной копии требуют решения оператора
  через будущий путь восстановления, с сохранёнными gate и журналом.

## 6. Вопросы мастер-агенту

Нет. Для приёмки существенно различать результаты изолированных проверок и ещё
не выполненную продуктовую матрицу.

## 7. Артефакты

- [artifacts/compose_fault_fixture.sh](./artifacts/compose_fault_fixture.sh) — раздельные
  временные проекты и тома, без клиентских данных, для повторения отказа и задержки
  с профилем MCP и без него.

## 8. Итерации исправлений

Итераций после формального ревью пока нет.
