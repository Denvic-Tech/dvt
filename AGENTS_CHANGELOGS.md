### 2026-01-29 17:15:00
- В `process_graph_op` добавлена проверка изменений `input_values` относительно актуальных значений в БД: если изменилось только `store_enabled`, то `should_infer_metadata = False`.

### 2026-01-28 12:15:00
- Добавлена нода `DataFrameSetTimezone` (`src/nodes/transform/df_set_timezone.py`) для установки временной зоны datetime-колонки.
- Нода поддерживает как локализацию naive datetime (`tz_localize`), так и конвертацию между зонами (`tz_convert`).

### 2026-01-26 15:42:51
- Исправлена сборка типизированной meta для query-executors в `core/db/read_v2/query/executors/ch.py` и `core/db/read_v2/query/executors/sql.py`.
- Повторно запущен memory benchmark и подтверждено, что `Period` сохраняет тип DATETIME после последующих нод.
- Сформирован отчет о фиксе в `tmp/period_type_fix_report_2026-01-26_15-42-51.md`.
### 2026-01-26 16:37:30
- Добавлено автоопределение формата JSON пайплайна для memory_benchmark с конвертацией UI формата в internal.
### 2026-01-26 17:01:43
- Запущен memory benchmark для пайплайна `tmp/pipelines/df-metadata-types-error.json` с отчетом `tmp/df-metadata-types-error-report.txt`.
### 2026-01-27 14:45:39
- Исправлено определение числового типа для numpy-скаляров в `core/db/read_v2/query/planner.py`, чтобы корректно выбирать агреггации по числовым partition_col.
### 2026-01-27 10:59:51
- Добавлены unit-тесты для `LocalCacheManager` с сериализацией через `core.dump_engine.dump`/`core.dump_engine.load`.
### 2026-01-27 12:17:01
- Добавлены интеграционные фикстуры контейнеров, подключений и клиентов для всех типов `ConnectionType`.
### 2026-01-27 12:29:03
- Добавлены интеграционные тесты RedisCacheManager с сериализацией через core.dump_engine.
### 2026-01-27 13:23:12
- Добавлены защитные пропуски интеграционных тестов при отсутствии Docker и недостающие фикстуры.
- Обновлены grpc-тесты кеша/индекса под актуальные сигнатуры и префиксы ключей.
- Добавлены заглушки shared_cache/shared_index_store для grpc менеджеров.
### 2026-01-27 13:34:52
- Исправлена обработка конфигов проектных настроек для bulk-insert и PK при записи в БД.
- Обновлены S3 storage options для корректной работы с MinIO (checksum/SSL/path style).
- Исправлены обновления graph_nodes и мелкие настройки интеграционных контейнеров.
### 2026-01-27 16:35:26
- Добавлен pre-commit скрипт проверки импортов по архитектурным границам в `scripts/.pre_commit/check_import_boundaries.py`.
### 2026-01-27 16:38:22
- Переведены правила проверки импортов на словарь `RULES` для удобного расширения в `scripts/.pre_commit/check_import_boundaries.py`.
### 2026-01-27 16:39:37
- Добавлены русские комментарии к полям `RULES` в `scripts/.pre_commit/check_import_boundaries.py`.
### 2026-01-27 16:42:47
- Добавлены настройки override для внешнего модуля `docker` и константа `ALLOWED_CONTRACTS_MODULE` в `scripts/.pre_commit/check_import_boundaries.py`.
### 2026-01-28 16:01:33
- Обновлен `PydanticType` для сериализации JSON через `TypeAdapter` и корректного JSONB-резолва в `src/models/sa_types.py`.
- Поле `QueueTopic.columns_schema` переведено на `PydanticType` для хранения в JSONB.
- Правила autogenerate миграций обновлены для JSONB-типов в `migrations/env.py`.
### 2026-01-28 16:41:00
- Добавлены CRUD-модули для `QueueTopic` в `src/crud/queue_topic` и `src/crud/asyncio/queue_topic`.
- Добавлены фикстуры и unit/integration тесты для CRUD `QueueTopic`.
### 2026-02-02 11:50:16
- Добавлены HTTP-схемы для CRUD `QueueTopic` в `src/schemas/http/queue_topic.py`.
- Реализованы CRUD-роуты `QueueTopic` в `services/gateway/routes/queue_topic/crud.py`.
### 2026-02-02 12:14:29
- Подключен роутер `QueueTopic` в `services/gateway/main.py`.
- Добавлены unit-тесты CRUD-роутов `QueueTopic` в `tests/unit/services/gateway/routes/queue_topic/test_crud.py`.
- Добавлена фикстура `db_session` для gateway-тестов в `tests/unit/services/gateway/conftest.py`.
### 2026-02-02 12:15:02
- Подключены фикстуры `app_config` и `router_config` в `tests/unit/services/gateway/conftest.py`.
### 2026-02-02 12:15:31
- Обновлен `DATABASE_URL` в `tests/unit/services/gateway/fixtures/config.py` на валидную postgres-схему для AppConfig.
### 2026-02-02 12:16:03
- Экспортирован `router` в `services/gateway/routes/queue_topic/__init__.py` для корректного подключения в `main.py`.
### 2026-02-02 12:49:08
- Переписаны HTTP-схемы `QueueTopic` на `pystructor` в `src/schemas/http/queue_topic.py`.
### 2026-02-02 12:52:51
- Добавлен `from_attributes` в `QueueTopicReadSchema` для корректного `model_validate` в `src/schemas/http/queue_topic.py`.
### 2026-02-02 17:59:06
- Добавлены `JSONOutputBaseNode` и метакласс `JSONOutputNodeMeta` в `src/node_dsl`.
- Обновлены экспорты `node_dsl` для JSON output нод.
### 2026-02-03 11:48:28
- Подготовлен отчет по менеджерам кеша/индекса PipelineProcessor и стратегиям развития кеширования в `tmp/pipeline_cache_report.md`.
### 2026-02-04 22:46:41
- Исправлена сериализация сегментов ключей индекса без префикса имени класса в `core/storage/index/base_key.py`.
- Возвращены значения по умолчанию для `output_name` и `hashed_inputs` в `src/caching/entries.py`, чтобы тесты PDF-индексов проходили.
### 2026-02-04 22:47:33
- Добавлены значения по умолчанию для полей `part_no`, `total_parts`, `rows` в `src/caching/entries.py`, чтобы убрать конфликт dataclass-наследования.
### 2026-02-04 22:53:22
- Возвращено требование префикса имени класса в индекс-ключах в `core/storage/index/base_key.py`.
- Возвращены обязательные поля для `DataIndexCacheEntry`/`PDFIndexEntry` в `src/caching/entries.py`.
- Обновлены unit-тесты индекс-ключей и кеш-энтри под префиксные ключи и обязательные поля в `tests/unit/core/storage/index/test_base_key.py`, `tests/unit/core/storage/index/test_storage.py`, `tests/unit/src/caching/test_entries_and_keys.py`.
### 2026-02-04 22:53:59
- Актуализирован unit-тест на пустой `DetailedKey` под поведение префиксного ключа в `tests/unit/core/storage/index/test_base_key.py`.

### 2026-02-05 11:08:33
- Добавлены интеграционные тесты для RedisIndexManager с сериализацией через core.dump_engine.

### 2026-02-05 11:17:37
- Расширены интеграционные тесты RedisIndexManager: разные ключи и entries, partial key query, mixed payloads, проверки через Redis клиент.

### 2026-02-05 11:28:17
- Исправлен Sequence в src/caching/protocols.py для корректной инициализации tuple.

### 2026-02-05 11:29:46
- Исправлено определение полного ключа в RedisIndexManager для ключей с префиксом имени класса.

### 2026-02-05 12:14:34
- В `docker/builder.Dockerfile` добавлен флаг `BUILD_BINARIES` для условной сборки Nuitka и создана директория `/build` даже при пропуске сборки.
- В `docker-compose.dev.yaml` добавлен аргумент `BUILD_BINARIES=0` для ускорения dev-сборок.
- В `docker-compose.prod.override.yaml` добавлен аргумент `BUILD_BINARIES=1` для prod-сборок с бинарниками.

### 2026-02-05 12:24:18
- Добавлен `docker/prod-builder.Dockerfile` для prod-сборок с Nuitka и заменой исходников, с копированием всего `/app`.
- В `docker/builder.Dockerfile` удалена сборка бинарников, оставлена подготовка окружения и `/build`, добавлено копирование `core`.
- Обновлены `services/*/docker/prod.Dockerfile`, чтобы использовать `dvt/prod-builder:latest` без условий и replace-скриптов.
- Обновлен `docker-compose.prod.override.yaml` для сборки `dvt/prod-builder:latest`.
- В `publish_images` добавлен `--profile build` для сборки prod-builder в `.gitlab-ci.yml`.
- Убраны dev-аргументы сборки из `docker-compose.dev.yaml`.

### 2026-02-05 13:51:20
- Добавлены e2e-фикстуры контейнеров orchestrator, task-worker, task-scheduler и gateway в `tests/e2e/fixtures/containers.py`.

### 2026-02-05 15:02:19
- Добавлен e2e smoke-тест контейнеров в `tests/e2e/test_containers_smoke.py`.

### 2026-02-06 12:10:30
- Реализовано кеширование JSON-выходов для JSON-нод в `src/node_dsl/base_node/json_output.py` (очистка старого кеша и сохранение нового результата в data cache/index по `JSONKey`).
- Исправлен `LocalIndexManager` для корректной работы с префиксом имени класса в индекс-ключах и добавлено удаление по префиксу в `src/managers/index_manager/local.py`.
- Добавлены unit-тесты кеширования JSON-выходов в `tests/unit/src/nodes/json/test_json_output_cache.py`.

### 2026-02-06 12:52:13
- Добавлен роут просмотра JSON-выходов нод: `services/gateway/routes/project/data/json.py` (GET `/projects/{project_id}/json/{node_id}`) и схема ответа `services/gateway/routes/project/data/schemas.py`.
- Подключен JSON-роутер в `services/gateway/routes/project/router.py`.
- Добавлено исключение `JSONNotFound` в `src/exception_registry/errors_list/gateway/project.py` для 404-ответов при отсутствии JSON в кеше/индексе.

### 2026-02-06 13:57:53
- Исправлена ошибка Postgres `COALESCE types text and boolean cannot be matched` в batch-update нод: добавлены явные `CAST(... AS BOOLEAN)` для `selected` и `store_enabled` в `src/crud/asyncio/graph/graph_nodes/update.py` и вынесена сборка запроса в `build_update_graph_nodes_stmt`.
- Добавлены unit и integration тесты на регрессию для обновления граф-нод в `tests/unit/src/crud/asyncio/graph/graph_nodes/test_update_graph_nodes_stmt.py` и `tests/integration/src/crud/asyncio/graph/graph_nodes/test_update_graph_nodes_integration.py`.

### 2026-02-06 14:02:52
- Исправлен интеграционный тест обновления graph-nodes под Windows: добавлена установка `WindowsSelectorEventLoopPolicy` для совместимости psycopg async и обновление ORM-объекта через `session.refresh()` после Core UPDATE в `tests/integration/src/crud/asyncio/graph/graph_nodes/test_update_graph_nodes_integration.py`.

### 2026-02-06 15:25:06
- Реализована нода `DataFrameToJson` (`src/nodes/json/df_to_json.py`): конвертация `dd.DataFrame` в Python-словарь и запись результата в `output`.
- Добавлены unit-тесты для `DataFrameToJson` в `tests/unit/src/nodes/json/test_df_to_json.py`.

### 2026-02-06 20:32:49
- Обновлён метакласс `BaseNodeMeta` для поддержки наследуемых `InputField`/`OutputField` (глобальный инпут `variables` теперь материализуется у всех нод и попадает в определения нод) в `src/node_dsl/node_meta/base.py`.
- Добавлен unit-тест на наследуемое базовое input-поле в `tests/unit/src/node_dsl/test_node_field_defaults.py`.
- Усилена изоляция интеграционных тестов БД (drop/create схемы на тест) в `tests/integration/fixtures/db.py`.

### 2026-02-06 20:41:38
- Исправлено распространение пропусков по графу: ноды, зависящие от пропущенной (например, из-за ошибки валидации), теперь тоже помечаются как `skipped`, чтобы не падать на `NodeInputError` при сборке входов (`src/pipeline/processor.py`).
- Добавлен unit-тест на регрессию для цепочки зависимостей после `NodeValidationError` в `tests/unit/src/pipeline/test_processor.py`.

### 2026-02-06 21:44:32
- Исправлена обработка `Ellipsis` как значения входа: теперь такие значения игнорируются при инициализации ноды, чтобы необязательные инпуты (включая глобальный `variables`) не падали на базовой валидации (`src/node_dsl/base_node/base.py`).
- Базовая валидация учитывает `optional` для `InputField` и не требует значения для опциональных полей (`src/node_dsl/base_node/mixins/validate_node.py`).
- Добавлены unit-тесты на поведение `Ellipsis` для опциональных и обязательных полей (`tests/unit/src/node_dsl/test_node_field_defaults.py`).

### 2026-02-06 22:17:56
- Подготовлено ТЗ и план реализации фичи совместной работы над проектом в `tmp/tech_spec_project_collaboration.md`.

### 2026-02-07 01:33:56
- Добавлена поддержка множественных подключений для `IO.VARIABLE` (сбор в словарь `{variable_name: VariableOutput}`) в сборке пайплайна и утилитах графа: `src/utils/graph.py`, `src/pipeline/graph_utils.py`.
- Расширена внутренняя модель `NodeInput` для хранения списка линков и обновлены связанные участки выполнения/валидации пайплайна: `src/schemas/internal/node_data.py`, `src/pipeline/processor.py`, `src/pipeline/validation.py`.
- Добавлены unit-тесты на множественные подключения переменных в `tests/unit/src/pipeline/test_graph_utils.py` и `tests/unit/src/utils/test_graph.py`.

### 2026-02-09 11:27:06
- Исправлена нода `DataFrameUnion` (`src/nodes/transform/df_union.py`): сделан безопасный `reset_index()` для Dask через `map_partitions` с уникальными именами индексных колонок и добавлена проверка `column_mapping` на коллизии имён, чтобы не падать в `dd.concat/pd.concat` с `InvalidIndexError`.
- Добавлены unit-тесты на регрессию для дублей имён колонок (конфликт index/column и конфликт mapping) в `tests/unit/src/nodes/transform/test_df_union.py`.

### 2026-02-09 11:58:07
- Убран временный хотфикс `repartition(npartitions=10)` из `DataFrameUnion` (`src/nodes/transform/df_union.py`), так как он не связан с причиной `InvalidIndexError` и может ухудшать производительность/партиционирование без необходимости.

### 2026-02-09 18:22:26
- Исправлены типы `InputVariableValue`/`InputConstantValue` в `src/types/input_values.py`: корректная обработка дискриминатора `__dvt_type`, добавлены функции `parse_input_value` и `resolve_input_value` для нормализации и резолва значений.
- В `src/utils/graph.py` обновлена сборка пайплайна из графа: поддержаны структурированные входные значения `const/var` в `input_values` с обратной совместимостью для legacy-значений.
- В `src/pipeline/graph_utils.py` и `src/pipeline/processor.py` добавлен резолв `InputVariableValue` через `task.project_variables.variables` как при формировании `node_kwargs`, так и при расчете `constant_inputs` для cache fingerprint.
- Обновлены и добавлены unit-тесты для нового формата входов: `tests/unit/src/utils/test_graph.py`, `tests/unit/src/pipeline/test_graph_utils.py`, `tests/unit/src/pipeline/test_processor.py`, `tests/unit/src/types/test_input_values.py`.

### 2026-02-09 18:43:06
- Доработан резолв переменных в `src/pipeline/graph_utils.py`: `InputVariableValue` в константных инпутах теперь разрешается не только из `project_variables`, но и из переменных, полученных по link-входам типа `IO.VARIABLE` (включая несколько присоединенных `CreateVariable` нод).
- Обновлен расчет `constant_inputs` в `src/pipeline/processor.py`: для cache fingerprint используется объединенный контекст переменных (project variables + linked `variables`), чтобы не падать на `Variable not found` после успешной сборки kwargs.
- В `src/types/input_values.py` добавлена поддержка извлечения значения из объектов переменных (`VariableOutput`) при `resolve_input_value`.
- Расширены unit-тесты: добавлены кейсы резолва из linked `CreateVariable` и приоритета linked-переменных при конфликте имени с project variable в `tests/unit/src/pipeline/test_graph_utils.py`, `tests/unit/src/pipeline/test_processor.py`, `tests/unit/src/types/test_input_values.py`.

### 2026-02-09 19:33:42
- Добавлена миграция `migrations/versions/0025_migrate_graph_node_input_values_to_inputvalue_objects.py` для преобразования `graph_nodes.input_values` в формат `InputValue`-объектов.
- В `upgrade` реализовано обновление только не-конвертированных значений: элементы, где уже есть `__dvt_type` со значением `var` или `const`, остаются без изменений; остальные оборачиваются в `{\"__dvt_type\": \"const\", \"variable\": <старое_значение>}`.
- Миграция выполняется SQL-выражением по `JSONB` и затрагивает только строки `graph_nodes`, где есть хотя бы один не-конвертированный input.

### 2026-02-09 19:39:17
- Доработан `downgrade` в `migrations/versions/0025_migrate_graph_node_input_values_to_inputvalue_objects.py`: обработка выполняется только для элементов с `__dvt_type = \"const\"`.
- При откате для `const` извлекается `variable`, а при его отсутствии используется fallback на `value`; элементы с `__dvt_type = \"var\"` и остальные значения оставляются без изменений.

### 2026-02-10 12:45:34
- Реализована унификация входных значений через общий `NodeInputValue` с дискриминатором `__dvt_type` (`var|const|link`) в `src/types/input_values.py`; добавлены типы runtime-входов, итератор link-значений и парсинг legacy-формата `NodeInput(type=..., value=...)`.
- Обновлена внутренняя модель `NodeData` в `src/schemas/internal/node_data.py`: `inputs` теперь хранит нормализованные runtime-значения, добавлена совместимость со старым классом `NodeInput`/`NodeInputType`.
- Переписаны runtime-участки на новый формат без проверки `NodeInputType`: `src/utils/graph.py`, `src/pipeline/graph_utils.py`, `src/pipeline/validation.py`, `src/pipeline/processor.py`; удалён неиспользуемый импорт `NodeInput` из `src/caching/entries.py`.
- Обновлены экспорты типов в `src/types/__init__.py` и unit-тесты `tests/unit/src/types/test_input_values.py`, `tests/unit/src/utils/test_graph.py`.
- Прогнаны целевые unit-тесты: `tests/unit/src/types/test_input_values.py`, `tests/unit/src/utils/test_graph.py`, `tests/unit/src/pipeline/test_graph_utils.py`, `tests/unit/src/pipeline/test_processor.py`, `tests/unit/src/pipeline/test_validation.py` (23 passed).
- Добавлена заметка в `AGENTS_TIPS.md` с паттерном унификации runtime/UI инпутов и сохранением обратной совместимости legacy-формата.

### 2026-02-10 13:03:26
- Исправлены падения unit/integration тестов после перехода на `NodeInputValue`.
- Обновлен тест DTO `tests/unit/src/dto/test_graph_dto.py` под новый формат `inputValues` с дискриминатором и проверкой через `parse_node_input_value`.
- Устранена мутация session-fixture `types_test_dataframe` в `tests/unit/src/managers/cache_manager/local/test_with_core_dump_load.py` (используется копия DataFrame), что убрало каскадное падение интеграционного теста Redis.
- Добавлена защитная обработка отсутствующих колонок в `tests/integration/src/managers/cache_manager/redis/test_with_core_dump_load.py` (`drop(..., errors="ignore")`).
- Исправлена нода записи в БД `src/nodes/write/write_df_to_db.py`: `index_col` теперь прокидывается в `build_table_from_df` как `primary_key_cols` при создании таблицы, что восстановило проверку PK в Oracle integration тесте.
- Расширена совместимость парсинга входных значений в `src/types/input_values.py`: поддержаны оба ключа дискриминатора `__dvt_type` и `dvt_type`.
- Выполнен полный прогон `pytest tests/unit tests/integration -q`: 537 passed, 0 failed.

### 2026-02-11 13:11:29
- Подготовлен детальный план реализации функционала `subgraph` и сохранен в `tmp/subgraph_implementation_plan.md`.
- В плане описаны изменения моделей/CRUD/роутов/схем, миграции, совместимость с UI и примеры кода с ссылками на исходники.

### 2026-02-11 13:26:04
- Реализована модель `Subgraph` (`src/models/subgraph.py`), добавлены связи в `Project`, а также поле `subgraph_id` в `GraphNode` и `GraphEdge`.
- Добавлены HTTP-схемы и DTO для `subgraph`, расширены схемы/DTO `graph_node` и `graph_edge` полем `subgraphId`.
- Добавлен CRUD для `subgraphs` в sync/async слоях (`src/crud/graph/subgraphs`, `src/crud/asyncio/graph/subgraphs`) и обновлены экспорты `__init__.py`.
- Обновлен `src/crud/graph/common.py`: теперь `get_graph_by` возвращает также список `subgraphs`.
- Обновлены gateway-роуты графа: `GET /projects/{project_id}/graph` возвращает `subgraphs`, а `graph-ops` поддерживает `subgraphs_to_create/update/delete` и ответные поля по subgraph-операциям.
- В `graph-ops` добавлена очистка `subgraph_id` у нод/ребер перед удалением subgraph и исключение metadata inference для patch-операций, где меняется только `subgraphId`.
- Добавлены и обновлены тесты DTO/CRUD графа для `subgraph` и `subgraphId` (`tests/unit/src/dto/test_graph_dto.py`, `tests/integration/src/crud/graph/subgraphs/*`, `tests/integration/src/crud/graph/test_common.py`).

### 2026-02-11 13:43:21
- Подготовлен список технических изменений для frontend-интеграции subgraph и сохранен в `temp/subgraphs_frontend_integration.md`.
- В документ добавлены API-контракты, примеры payload/response, требования к обновлению frontend-состояния и примечание про отсутствие миграции.

### 2026-02-16 14:40:32
- Добавлен подробный `README.md` для пакета `core/db/read_v2` с описанием назначения, архитектуры и публичных точек входа (`resolve_planner`, `resolve_executor`, `frame_from_executor`).
- Подготовлено детальное сравнение `read_v2` с нативными `dask.dataframe.read_sql_table` и `dask.dataframe.read_sql_query`, включая отличия по API, партиционированию и диалектной поддержке.
- Задокументированы режимы `table/query`, структуры планов (`ReadPlan`, `SQLReadPlan`, `QueryPlan`), поддерживаемые режимы `partition_grouping` и текущие ограничения реализации.

### 2026-02-16 14:48:59
- Добавлены unit-тесты `tests/unit/core/db/read_v2/test_dask.py` для проверки поведения `core/db/read_v2/dask.py::frame_from_executor`.
- Зафиксировано в тестах, что при сборке `dask.dataframe` через `from_delayed` `read_v2` возвращает `unknown divisions` (`known_divisions == False`) в table/query single-shot сценариях.
- Добавлен тест на fallback-поведение при пустом списке сегментов (возврат пустого DataFrame по `meta` без вызовов `load_partition`).
- Выполнен таргетный прогон `pytest tests/unit/core/db/read_v2/test_dask.py -q` (3 passed).

### 2026-02-16 14:58:27
- Существенно расширен unit-набор для `read_v2`: добавлены тесты `test_grouping_spec.py`, `test_partitioning_utils.py`, `test_partitioning_strategies.py`, `test_grouping_builder.py`, `test_query_planner.py`, `test_resolver.py`, `test_sql_planner_helpers.py`, `test_models.py`, `test_utils_ch.py`, `test_utils_sql.py`.
- В тестах покрыты сценарии по режимам table/query, стратегиям сегментации, резолву диалектов (PostgreSQL/MySQL/MSSQL/SQLServer/Oracle/ClickHouse), обработке `partition_grouping` и вспомогательным утилитам.
- Отдельными проверками зафиксированы текущие ограничения эффективности: `unknown divisions` в Dask-результате, count-запрос на каждый bin в числовой/дата-сегментации и обязательный `count(*)` в query offset fallback.
- Выполнен полный прогон `pytest tests/unit/core/db/read_v2 -q` (90 passed).

### 2026-02-16 15:14:24
- Добавлены integration-тесты `tests/integration/core/db/read_v2/test_read_v2_integration.py` для прямой проверки `read_v2` (table/query mode) на PostgreSQL, MySQL, Oracle и ClickHouse, а также условного MSSQL-сценария.
- В integration-набор включены проверки: базовое чтение таблицы, hash-grouping, query segmented чтение, query offset fallback и проблемные кейсы с `limit`/`offset`.
- Зафиксированы и покрыты тестами текущие дефекты/ограничения: падение table hash-grouping для MySQL (`%` в SQL через PyMySQL), падение numeric hash-grouping для PostgreSQL (`hashtext(integer)`), ошибка query offset без `partition_col` в Oracle (нет поддержки OFFSET) и mismatch сегментов в ClickHouse при `limit`.
- Реализован условный `skip` MSSQL-интеграций при отсутствии `pyodbc` в окружении.
- Выполнен полный прогон `pytest tests/integration/core/db/read_v2/test_read_v2_integration.py -q` (18 passed, 3 skipped).

### 2026-02-16 15:20:53
- Подготовлен подробный план апгрейда `read_v2` и сохранен в `tmp/read_v2_upgrade_plan.md`.
- В плане описаны этапы оптимизации производительности и RAM-эффективности: внедрение known divisions, снижение SQL fan-out в planner, диалектные багфиксы и усиление executor-стратегий.
- Добавлены ссылки на исходный код `core/db/read_v2/*` и примеры кода/SQL для целевых изменений.

### 2026-02-16 15:29:24
- План апгрейда переориентирован на новую версию `read_v3`: файл переименован в `tmp/read_v3_upgrade_plan.md`.
- В документе зафиксирован strict fail-fast контракт: удалены fallback-подходы, для непредвиденных сценариев предусмотрены явные типизированные ошибки.
- Добавлены требования по поддержке разных типов данных (numeric/string/datetime/bool/uuid и сложные типы через детерминированный hash-adapter) и раздел по known divisions как обязательной части архитектуры.
- Добавлен обязательный этап сравнительного профилирования `read_v2` vs `read_v3` через `testing_services/memory_benchmark` с командами запуска и требованиями к отчетности в `experiments/`.

### 2026-02-16 16:08:56
- Реализован новый пакет `core/db/read_v3` (strict/fail-fast) с отдельными модулями `errors`, `models`, `dialects`, `planner`, `executors`, `partitioning`, `resolver` и `dask`-сборкой с known divisions.
- Добавлена поддержка стратегий `range/hash` для разных типов ключей (numeric/string/date/datetime/bool/unknown), включая автоматический переход к `hash` для nullable/non-orderable ключей без silent fallback-поведения.
- В `read_v3` добавлены строгие проверки: обязательный `partition_col` в query-mode, запрет `limit` в strict-режиме, валидация divisions, контроль monotonic index и ограничение `max_rows_per_partition` в executor.
- Добавлены unit-тесты `tests/unit/core/db/read_v3/*` (14 passed): adapters/divisions, dask-known-divisions, resolver и e2e-сценарии на SQLite для table/query режимов.
- Добавлены benchmark-ноды `src/nodes/testing/read_benchmark_db_nodes.py` и pipeline-файлы `testing_services/memory_benchmark/read_v2_sqlite_benchmark.json` и `testing_services/memory_benchmark/read_v3_sqlite_benchmark.json` для сравнения `read_v2` и `read_v3`.
- Для совместимости `memory_benchmark` с актуальной схемой `TaskInternal` обновлен `testing_services/memory_benchmark/utils.py` (в `build_task` добавлены `project_settings` и `project_variables`).
- Выполнено сравнение через `testing_services/memory_benchmark`: отчеты сохранены в `tmp/read_v2_memory_benchmark.txt` и `tmp/read_v3_memory_benchmark.txt`, итоговый отчет эксперимента сохранен в `experiments/2026-02-16T16-08-33_read-v3-sqlite-memory-benchmark.md`.

### 2026-02-16 17:17:13
- Добавлены интеграционные benchmark-конфиги для ClickHouse-таблицы `csv_sale_from_arustamov` (49_690_000 строк): `testing_services/memory_benchmark/read_v2_clickhouse_csv_groupby_benchmark.json` и `testing_services/memory_benchmark/read_v3_clickhouse_csv_groupby_benchmark.json`.
- Для сценария `read -> groupby -> materialize` переключен `partition_col` на `Номер чека`; downstream-нода `DataFrameGroupByAgg` агрегирует `Сумма к оплате` по `Товарная группа`.
- Исправлен дефект `read_v2` в `core/db/read_v2/executors/ch.py`: при пустом ClickHouse-сегменте теперь возвращается пустой DataFrame с ожидаемой схемой, а не с пустым списком колонок.
- Для стабильного сравнения `read_v3` обновлена benchmark-нода `ReadClickHouseTableV3BenchmarkNode` (`src/nodes/testing/read_benchmark_db_nodes.py`) с увеличенным пулом SQLAlchemy (`pool_size/max_overflow/pool_timeout`), чтобы избежать `QueuePool limit` при параллельной загрузке сегментов.
- Выполнены прогоны `testing_services/memory_benchmark` и сохранены отчеты: `tmp/read_v2_clickhouse_csv_groupby_benchmark.txt`, `tmp/read_v3_clickhouse_csv_groupby_benchmark.txt`.
- Зафиксирована разница по divisions на одинаковых параметрах (`npartitions=16`): `read_v2` -> `known_divisions=False`, `read_v3` -> `known_divisions=True` с явными границами диапазонов.

### 2026-02-16 18:47:05
- Оптимизирован `read_v3` executor (`core/db/read_v3/executors/sql.py`): удалено накопление чанков и `pd.concat`, вместо этого введено bounded-чтение одним SQL-запросом с `row_cap = max_rows_per_partition + 1` и strict-проверкой переполнения сегмента.
- Уменьшены лишние копии DataFrame в `read_v3`: убран `df.copy()`, удаление helper-колонок выполняется in-place, переупорядочивание колонок происходит только при реальной необходимости.
- Расширены диалекты `read_v3`: добавлен метод `cap_rows_sql` в `core/db/read_v3/dialects/base.py` и специализированная реализация для MSSQL в `core/db/read_v3/dialects/mssql.py`.
- Добавлены unit-тесты `tests/unit/core/db/read_v3/test_executor_sql.py` (проверка bounded-ошибки, очистки helper-колонок и SQL cap для MSSQL); выполнен прогон `pytest tests/unit/core/db/read_v3 -q` (17 passed).
- Обновлены benchmark-ноды (`src/nodes/testing/read_benchmark_db_nodes.py`): для `ReadClickHouseTableV3BenchmarkNode` добавлены управляемые параметры пула (`db_pool_size/db_max_overflow/db_pool_timeout`), для `MaterializeDataFrameRowsBenchmarkNode` добавлен `num_workers` и явный `compute(..., scheduler='threads')`.
- Обновлены ClickHouse benchmark-пайплайны для сценария под ограниченную RAM: `npartitions=64`, `num_workers=2`, а для `v3` дополнительно `max_rows_per_partition=1_500_000` и параметры пула БД.
- Выполнено повторное сравнение в Docker через сервис `docker-compose.tests.yaml:memory_benchmark` с лимитом `8 GB` (override `tmp/docker-compose.memory_benchmark.8g.yaml`):
  - `read_v2` под тем же пайплайном завершился `Killed` (OOM в контейнере, отчет не сформирован);
  - `read_v3` успешно завершился, отчет `tmp/read_v3_clickhouse_csv_groupby_benchmark_docker_8g.txt` (`Duration 229.722s`, `RSS peak 1166.73 MiB`, `RSS end 734.43 MiB`).
- Добавлен отчет эксперимента: `experiments/2026-02-16T18-47-50_read-v3-docker-8g-clickhouse.md`.

### 2026-02-16 19:22:21
- Подготовлен подробный план рефакторинга сервиса `testing_services/memory_benchmark` и сохранен в `tmp/memory_benchmark_refactor_plan.md`.
- В плане зафиксированы текущие неудобства, целевая структура хранения pipeline JSON и артефактов запусков, roadmap по улучшению UX/архитектуры и предложения по фичам.
- Отдельно рассмотрены: целесообразность MCP-сервера для агентного запуска benchmark, стратегия переноса из `testing_services` в `services`, а также необходимость документировать запуск `docker-compose.tests.yaml` как override к `docker-compose.dev.yaml`.

### 2026-02-16 20:25:12
- Реализован основной этап рефакторинга `testing_services/memory_benchmark`: добавлены структурированные артефакты запусков в `tmp/memory_benchmark/runs/<run_id>/` (`config.json`, `report.txt`, `report.json`, `env.txt`), новые CLI-флаги `--report-json`, `--output-root`, `--run-id`, `--validate-only`, а также JSON-отчеты со схемой `1.0`.
- Обновлен runtime benchmark-сервиса (`testing_services/memory_benchmark/runner.py`, `testing_services/memory_benchmark/utils.py`, `testing_services/memory_benchmark/patching.py`, `testing_services/memory_benchmark/main.py`, `testing_services/memory_benchmark/report.py`) с поддержкой validate-only режима, сохранением окружения запуска и совместимостью legacy-путей пайплайнов.
- Перестроена структура сценариев: JSON-пайплайны перенесены из корня `testing_services/memory_benchmark` в `testing_services/memory_benchmark/pipelines/examples` и `testing_services/memory_benchmark/pipelines/benchmarks/*`; добавлены JSON Schema-файлы `testing_services/memory_benchmark/schemas/benchmark_run.schema.json` и `testing_services/memory_benchmark/schemas/benchmark_report.schema.json`.
- Обновлена документация запуска и compose-override логики в `testing_services/memory_benchmark/README.md` и корневом `README.md`; в `docker-compose.tests.yaml` удалена неиспользуемая переменная `MEM_BENCH_CONFIG`; в `core/db/write_v2/README.md` обновлен путь к benchmark-сценарию.
- Добавлены unit-тесты для нового CLI/утилит (`tests/unit/testing_services/memory_benchmark/test_cli.py`, `tests/unit/testing_services/memory_benchmark/test_utils.py`), выполнены проверки `compileall` для `testing_services/memory_benchmark` и `pytest tests/unit/testing_services/memory_benchmark -q` (4 passed).

### 2026-02-16 20:38:01
- Доведён рефактор `memory_benchmark` по Phase 1/2 (без MCP и без выноса ядра в библиотечный модуль): добавлены новые режимы CLI `--dry-run`, `--matrix`, `--compare-candidate-*`, `--pipeline-format`, `--preset`, а также управляемые override-флаги `--npartitions`, `--num-workers`, `--max-rows-per-partition`.
- Реализован безопасный compare-режим без мутации git-дерева (`run_safe_compare` в `testing_services/memory_benchmark/patching.py`) с итоговым `compare_report.json/txt`; patch-flow оставлен как legacy unsafe-режим с явным предупреждением.
- Добавлен matrix-runner (`testing_services/memory_benchmark/matrix.py`, `run_matrix_benchmark` в `testing_services/memory_benchmark/runner.py`) с поддержкой JSON/YAML-конфигов, параметрической сетки и explicit cases; итог matrix сохраняется в `matrix_report.json/txt`.
- Добавлены ресурсные пресеты и слияние override-ов (`testing_services/memory_benchmark/config.py`), внедрено применение preset/CLI/matrix override-ов к pipeline inputs в `testing_services/memory_benchmark/utils.py`.
- Разделён отчётный слой на text/json рендереры: `testing_services/memory_benchmark/report_text.py` и `testing_services/memory_benchmark/report_json.py`, сохранён совместимый фасад `testing_services/memory_benchmark/report.py`.
- Обновлены схемы артефактов (`testing_services/memory_benchmark/schemas/*.schema.json`) и документация (`testing_services/memory_benchmark/README.md`) под новые режимы, включая safe compare и matrix workflow.
- Добавлены новые unit-тесты `tests/unit/testing_services/memory_benchmark/test_config.py` и `tests/unit/testing_services/memory_benchmark/test_matrix.py`, расширены `test_cli.py` и `test_utils.py`; выполнен прогон `pytest tests/unit/testing_services/memory_benchmark -q` (10 passed) и `compileall`.

### 2026-02-17 13:07:22
- Проанализировано ТЗ `tmp/ТЗ_Ситилинк.md`: выделены конкретные требования Ситилинка к процессу DWH -> Parquet -> S3.
- Проведена сверка текущих возможностей DVT по исходному коду (extract/write/transform ноды, S3-менеджер, UI-контракт save parquet).
- Подготовлен и сохранен план внедрения отсутствующих фич в `tmp/plan_citilink_dwh_parquet.md` на русском языке, включая GAP-анализ, ссылки на исходный код и примеры кода.

### 2026-02-17 14:04:51
- Запущен полный набор интеграционных тестов `tests/integration` в окружении `.venv3.13` с Docker testcontainers; подтверждено стабильное прохождение после исправлений (`124 passed`).
- Исправлен `core/db/read_v2/query/planner.py`: генерация SQL для чтения метаданных и инференса типов сделана диалектно-безопасной (MSSQL без `LIMIT/FETCH NEXT 0`, ClickHouse с `LIMIT 0`-probe для получения колонок).
- Исправлен `core/db/read_v2/query/executors/sql.py`: для MSSQL убран некорректный `OFFSET/FETCH` в segmented query без `ORDER BY`, а `build_meta` сделан устойчивым через схему `WHERE 1=0`.
- Исправлен `src/crud/graph/common.py`: добавлена нормализация legacy `input_values` при чтении графа (`get_graph_by`), чтобы старые scalar/link payload корректно валидировались в `GraphNode`.

### 2026-02-17 14:09:55
- Исправлена регрессия в `core/db/read_v2/query/planner.py`: в метод `_resolve_column` возвращена инициализация `dialect_obj = resolve_sql_dialect(engine)`, устранен `NameError` в unit-тестах.
- Обновлен unit-тест `tests/unit/core/db/read_v2/test_query_planner.py`: мок-планнер принимает новый SQL probe для метаданных (`WHERE 1 = 0`) наряду с legacy `LIMIT 0 OFFSET 0`.
- Выполнен повторный прогон `pytest tests/unit/core/db/read_v2/test_query_planner.py` и полный `pytest tests/unit`: все тесты успешно пройдены (`530 passed`).

### 2026-02-17 14:48:23
- Переведены оставшиеся исходники с синхронного `src.crud` на `src.crud.asyncio`: обновлены роуты `queue_topic`, `project/variables`, `project/graph/common`, `project/crud`, а также воркер `services/task_worker/tasks/worker_tasks.py`.
- Добавлен недостающий async CRUD для переменных проекта: `src/crud/asyncio/project/project_variables.py`; расширены экспорты `src/crud/asyncio/project/__init__.py`.
- Актуализирован async CRUD графа `src/crud/asyncio/graph/common.py`: добавлена поддержка `subgraphs`, legacy-нормализация `input_values` и кросс-БД реализация без `jsonb_agg`.
- Для `src/models/app_config.py` добавлен async-неймспейс импорт (`src/crud/asyncio/auto_crud.py`), чтобы убрать прямую зависимость от sync CRUD.
- Обновлена нода `src/nodes/extract/read_queue_topic.py`: импорт на async CRUD, безопасный async/sync fallback чтения метаданных (без зависимости от `aiosqlite` для sync SQLite-тестов).
- Добавлены unit-тесты: `tests/unit/services/gateway/routes/project/test_variables.py`, `tests/unit/services/gateway/routes/project/test_graph_common.py`, `tests/unit/services/gateway/routes/project/test_crud_async.py`, `tests/unit/services/task_worker/tasks/test_worker_tasks.py`; обновлены gateway fixtures для override `get_async_session`.
- Добавлен integration-тест async CRUD переменных проекта: `tests/integration/src/crud/asyncio/project/test_project_variables.py`.
- Удалены тесты sync CRUD: `tests/unit/src/crud/project/read/*`, `tests/unit/src/crud/queue_topic/*`, `tests/integration/src/crud/graph/*`, `tests/integration/src/crud/queue_topic/*`.
- Выполнены проверки: `pytest tests/unit` (`522 passed`) и `pytest tests/integration` (`83 passed`).

### 2026-02-17 15:28:10
- Исправлена базовая валидация входов нод в `src/node_dsl/base_node/mixins/validate_node.py`: теперь для обязательных (`optional=False`) полей ошибка `NodeValidationError` поднимается как при `Ellipsis`, так и при явном `None`.
- Добавлен регрессионный unit-тест `tests/unit/src/node_dsl/test_node_field_defaults.py::TestInputFieldDefaults::test_none_input_fails_for_required_field` для сценария обязательного поля, в которое передан `None`.
- Добавлен unit-тест `tests/unit/src/nodes/extract/test_read_table_from_db_v2_validation.py`, подтверждающий, что `ReadTableFromDBV2` выбрасывает `NodeValidationError`, если `table_name=None`.
- Выполнен прогон `pytest tests/unit/src/node_dsl/test_node_field_defaults.py tests/unit/src/nodes/extract/test_read_table_from_db_v2_validation.py` (13 passed).

### 2026-02-17 15:30:46
- Исправлен новый баг в `src/node_dsl/base_node/mixins/validate_node.py`: проверка обязательных полей переведена на identity-сравнение (`is Ellipsis` / `is None`) вместо membership (`in (Ellipsis, None)`), чтобы не вызывать пользовательский `__eq__` у значений входа (в т.ч. у Dask DataFrame).
- Добавлен регрессионный unit-тест `tests/unit/src/node_dsl/test_node_field_defaults.py::TestInputFieldDefaults::test_validation_does_not_call_eq_when_checking_required_sentinel_values` для сценария, где `__eq__` значения бросает `NotImplementedError`.
- Повторно выполнен прогон `pytest tests/unit/src/node_dsl/test_node_field_defaults.py tests/unit/src/nodes/extract/test_read_table_from_db_v2_validation.py` (14 passed).

### 2026-02-17 15:43:51
- Исправлена причина падения `WriteDataFrameToDB` для ClickHouse при вставке в строковые колонки значений `np.nan` (`numpy.float64`): в `core/db/write_v2/clickhouse.py` добавлена нормализация string-like типов (`String`, `FixedString`, `LowCardinality(String)`) с конвертацией пропусков в `None` и значений не-строковых типов в `str`.
- Добавлены unit-тесты `tests/unit/core/db/write_v2/test_clickhouse.py`, покрывающие регрессионный кейс с `np.nan` в строковой колонке и вариант `LowCardinality(String)`.
- Добавлен integration-тест `tests/integration/src/nodes/write/test_write_df_to_db_clickhouse.py` для сценария записи через `WriteDataFrameToDB` в ClickHouse, проверяющий корректную вставку `NULL` вместо `np.nan` в `String`-колонке.
- Выполнен таргетный прогон `pytest tests/unit/core/db/write_v2/test_clickhouse.py tests/integration/src/nodes/write/test_write_df_to_db_clickhouse.py -q`: unit-тесты пройдены, integration-тест не выполнен локально из-за отсутствия доступа к Docker daemon (`CreateFile ... Отказано в доступе`).

### 2026-02-17 16:38:56
- Перепроверен integration-тест `tests/integration/src/nodes/write/test_write_df_to_db_clickhouse.py` после восстановления доступа к Docker: выявлена нестабильность из-за асинхронной вставки ClickHouse (`async_insert=1`, `wait_for_async_insert=0`), когда мгновенный `SELECT count()` может вернуть `0`.
- Обновлен integration-тест: добавлено короткое polling-ожидание (до 5 секунд) перед финальной проверкой количества строк, чтобы тест отражал фактическую eventual consistency async insert.
- Повторно выполнен прогон `pytest tests/integration/src/nodes/write/test_write_df_to_db_clickhouse.py -q` (1 passed).

### 2026-02-18 11:59:37
- Изучены материалы `tmp/ТЗ_Ситилинк.md` и `tmp/features_for_citilink.md`, выделены конкретные функциональные требования к универсальному DWH -> Parquet -> S3 пайплайну.
- Проведена сверка текущих возможностей DVT по `ReadTableFromDBV3`, `ReadQueryFromDBV3`, `SaveParquet`, UI-расширениям и тестовому покрытию; зафиксированы отсутствующие фичи и несоответствия контрактов UI/backend.
- Подготовлен и сохранен детализированный план внедрения отсутствующих возможностей в `tmp/plan_dwh_parquet_features_gap.md` (на русском, в Markdown, со ссылками на исходный код и примерами кода).

### 2026-02-18 12:32:51
- В `core/db/read_v3/planner/table.py` и `core/db/read_v3/planner/query.py` реализована поддержка `limit` в strict-режиме через глобально ограниченный relation до сегментации (с `ORDER BY partition_key` + dialect-specific `LIMIT/OFFSET`), без ослабления валидации `divisions`.
- Для `read_v3` добавлена валидация не-положительного `limit` (`ReadV3ConfigError: limit must be positive`) и расширены диагностические `extra_warnings` (включая значение `limit`).
- Обновлена нода `ReadQueryFromDBV3` (`src/nodes/extract/read_query_from_db_v3.py`): добавлен вход `limit` и прокидывание параметра в planner.
- Добавлены unit-тесты `tests/unit/core/db/read_v3/test_sqlite_e2e.py` на `table/query` режимы с `limit` (сохранение `known_divisions`, корректный состав строк) и на reject `limit <= 0`.
- Добавлены integration-тесты `tests/integration/core/db/read_v3/test_read_v3_integration.py` и `tests/integration/src/nodes/extract/test_read_db_v3_nodes.py` для end-to-end проверки `limit` в `core/db/read_v3`, `ReadTableFromDBV3` и `ReadQueryFromDBV3`.
- Добавлены unit-тесты нод `tests/unit/src/nodes/extract/test_read_table_from_db_v3.py` и `tests/unit/src/nodes/extract/test_read_query_from_db_v3.py`, фиксирующие корректную передачу `limit` из нод в planner.
- Выполнены прогоны: `pytest tests/unit/core/db/read_v3 tests/unit/src/nodes/extract/test_read_query_from_db_v3.py tests/unit/src/nodes/extract/test_read_table_from_db_v3.py -q` (23 passed) и `pytest tests/integration/core/db/read_v3/test_read_v3_integration.py tests/integration/src/nodes/extract/test_read_db_v3_nodes.py -q` (4 passed).
- Попытка запустить `ruff` через venv завершилась сообщением `No module named ruff` (локально недоступен в текущем окружении).

### 2026-02-18 12:40:46
- Упрощен контракт `read_v3` для table-mode: в `core/db/read_v3/planner/table.py` удален параметр `index_col`, оставлена одна пользовательская колонка партиционирования `partition_col`.
- Обновлена логика выбора ключа в planner: теперь используется `partition_col`, а при его отсутствии — fallback на одиночный PK; текст ошибки обновлен на `Provide partition_col or ensure table has a single-column PK`.
- Обновлена нода `ReadTableFromDBV3` (`src/nodes/extract/read_table_from_db_v3.py`): удалено входное поле `index_col` и удален его проброс в planner.
- Синхронизированы V3-вызовы и тесты: обновлен benchmark-узел `ReadTableFromDBV3BenchmarkNode` (`src/nodes/testing/read_benchmark_db_nodes.py`) и unit-тест `tests/unit/src/nodes/extract/test_read_table_from_db_v3.py`.
- Выполнены прогоны: `pytest tests/unit/core/db/read_v3 tests/unit/src/nodes/extract/test_read_query_from_db_v3.py tests/unit/src/nodes/extract/test_read_table_from_db_v3.py -q` (23 passed) и `pytest tests/integration/core/db/read_v3/test_read_v3_integration.py tests/integration/src/nodes/extract/test_read_db_v3_nodes.py -q` (4 passed).

### 2026-02-18 12:50:20
- Проанализированы последние 3 git-коммита (`9d21f14d`, `408366b3`, `a2a17e20`) с учетом изменений `read_v3`: поддержка `limit` и отказ от `index_col` в пользу `partition_col`.
- Актуализирован план в `tmp/plan_dwh_parquet_features_gap.md`: удалены устаревшие допущения про отсутствие `limit` и отсутствие integration для `read_v3`, добавлены фактические изменения и новые приоритеты по выравниванию UI/backend контракта.
- В обновленном плане зафиксирован новый обязательный шаг: удалить `index_col` из UI `ReadTableFromDBV3` и привести клиентский payload к единому ключу сегментации `partition_col`.

### 2026-02-18 13:12:33
- План в `tmp/plan_dwh_parquet_features_gap.md` полностью переписан под стратегию pipeline-first: инкремент реализуется через `ReadTableFromDBV3` (source + stage) и последующие `DataFrameJoin`/`DataFrameFilter`, без добавления специального incremental-режима в `Read*V3`.
- Проведена повторная сверка требований и возможностей DVT: зафиксировано, что критические недостающие фичи сосредоточены в `SaveParquet` (контракт порядка колонок, row-cap на файл, типовой контракт parquet, автоматический `DWH_Pack_ID`) и в UI-синхронизации `ReadTableFromDBV3` (удаление legacy `index_col`).
- В план добавлен отдельный опциональный блок на случай, если обновление stage должно запускаться внутри DVT: универсальная нода `ExecuteSQLCommand` без заказчик-специфики.

### 2026-02-18 14:11:39
- Проведен архитектурный аудит текущей реализации DVT с фокусом на границы сервисов, работу с Postgres и риски производительности/ресурсоемкости при множестве инсталляций на отдельных VM.
- Подтверждено по исходному коду, что `gateway`, `orchestrator`, `task_worker` и `task_scheduler` напрямую работают с БД и разделяют общий слой `src.db`/`src.crud`; зафиксированы связанные архитектурные риски (shared DB ownership, in-memory state, контрактный дрейф сервисов).
- Подготовлен и сохранен подробный отчет с рекомендациями в `tmp/architecture_review_db_and_services_2026-02-18.md` (Markdown, на русском, со ссылками на исходные файлы и примерами).

### 2026-02-18 15:40:56
- Исследована причина падения `WriteDataFrameToDB` с `Metadata mismatch found in from_delayed`: в путях чтения из БД фактические партиции иногда приходили с dtype `datetime64[us]`, тогда как `meta` формировался как `datetime64[ns]`.
- Исправлена нормализация datetime precision до `ns` в `core/db/dask_read.py` (`_apply_soft_casts`), `core/utils/dtype_coercion.py` (`apply_dtypes_and_casts`) и `core/db/read_v2/executors/base.py` (`_coerce_datetime_columns`), чтобы устранить mismatch `us/ns` до сборки/использования Dask DataFrame.
- Добавлены unit-тесты на регрессию `datetime64[us] -> datetime64[ns]`: обновлен `tests/unit/core/utils/test_dtype_coercion.py` и добавлен `tests/unit/core/db/test_dask_read.py`.
- Добавлен integration-тест контекста ошибки `tests/integration/src/nodes/write/test_write_df_to_db_clickhouse.py::test_write_dataframe_read_from_clickhouse_datetime64_us` для цепочки `ReadTableFromDB -> WriteDataFrameToDB` с `DateTime64(6)` в ClickHouse.
- Выполнен прогон `pytest tests/unit/core/utils/test_dtype_coercion.py tests/unit/core/db/test_dask_read.py` (11 passed); запуск integration-теста локально не выполнен из-за отсутствия доступа к Docker daemon (`CreateFile ... Отказано в доступе`).

### 2026-02-18 16:02:21
- Повторно запущен интеграционный тест `tests/integration/src/nodes/write/test_write_df_to_db_clickhouse.py -k datetime64_us` после предоставления доступа к Docker: выявлен флейк из-за асинхронной вставки ClickHouse (в логах вставка `rows=2`, но мгновенный `SELECT count()` возвращал `0`).
- Обновлен тест `tests/integration/src/nodes/write/test_write_df_to_db_clickhouse.py::test_write_dataframe_read_from_clickhouse_datetime64_us`: добавлено polling-ожидание до 5 секунд перед проверкой количества строк.
- Выполнен повторный прогон `pytest tests/integration/src/nodes/write/test_write_df_to_db_clickhouse.py -k datetime64_us` — тест проходит (`1 passed, 1 deselected`).

### 2026-02-18 17:02:49
- В `read_v3` добавлена поддержка `partition_grouping` для table/query режимов без ослабления strict-контракта `known_divisions`: реализован модуль `core/db/read_v3/partitioning/grouping.py` с адаптацией режимов V2 (`prefix`, `explicit_values`, `ranges`, `step`, `granularity`, `as_is`, `hash`, `quantiles/percentiles`) к V3-сегментам.
- Для безопасной работы divisions в V3 добавлен синтетический индекс сегмента: расширены модели `core/db/read_v3/models.py` (`ReadSegment.index_literal`, `ReadV3Plan.index_column_name`) и исполнитель `core/db/read_v3/executors/sql.py` (segment-local index literal, выбор индексной колонки через `index_column_name`, корректный meta/index для strict mode).
- Обновлены planner'ы `core/db/read_v3/planner/table.py` и `core/db/read_v3/planner/query.py`: добавлена ветка `partition_grouping`, введена проверка взаимной исключаемости `partition_grouping` и `partition_strategy`, сохранен legacy-путь `range/hash` для существующих сценариев.
- Расширен диалектный слой V3: в `core/db/read_v3/dialects/base.py` добавлены общие методы для grouping (`render_in_list`, `string_prefix_expr`, `quantile_expr`), реализованы `string_prefix_expr` в SQL-диалектах и `quantile_expr` для ClickHouse.
- Обновлены ноды `ReadTableFromDBV3` и `ReadQueryFromDBV3` (`src/nodes/extract/read_table_from_db_v3.py`, `src/nodes/extract/read_query_from_db_v3.py`): добавлен вход `partition_grouping` и его проброс в planner.
- Дополнены unit-тесты:
- `tests/unit/core/db/read_v3/test_sqlite_e2e.py` — кейсы `partition_grouping` по типам STRING/NUMERIC/DATETIME/BOOL, query-mode grouping и валидация конфликта `partition_grouping` + `partition_strategy`.
- `tests/unit/src/nodes/extract/test_read_table_from_db_v3.py` и `tests/unit/src/nodes/extract/test_read_query_from_db_v3.py` — проверка проброса `partition_grouping` из нод в planner.
- Дополнены integration-тесты:
- `tests/integration/core/db/read_v3/test_read_v3_integration.py` — table/query сценарии с `partition_grouping`.
- `tests/integration/src/nodes/extract/test_read_db_v3_nodes.py` — end-to-end `partition_grouping` через `ReadTableFromDBV3` и `ReadQueryFromDBV3`.
- Выполнены прогоны:
- `pytest tests/unit/core/db/read_v3 tests/unit/src/nodes/extract/test_read_query_from_db_v3.py tests/unit/src/nodes/extract/test_read_table_from_db_v3.py -q` (29 passed).
- `pytest tests/integration/core/db/read_v3/test_read_v3_integration.py tests/integration/src/nodes/extract/test_read_db_v3_nodes.py -q` (8 passed).
- В `AGENTS_TIPS.md` добавлена заметка про паттерн безопасной интеграции custom grouping в `read_v3` (синтетический индекс сегмента для strict `known_divisions` и нормализация SQLite `DATETIME`).

### 2026-02-18 18:03:14
- В `ReadTableFromDBV3` и `ReadQueryFromDBV3` завершено объединение API партиционирования в единый вход `partition_grouping`: удален вход `partition_strategy` из нод `src/nodes/extract/read_table_from_db_v3.py` и `src/nodes/extract/read_query_from_db_v3.py`.
- Обновлены planner'ы `core/db/read_v3/planner/table.py` и `core/db/read_v3/planner/query.py`: `partition_grouping.mode` теперь управляет как базовыми стратегиями (`range`/`hash`), так и custom-grouping режимами; для `hash` добавлен override числа сегментов через `buckets/mod`; удалена проверка конфликта с удаленным `partition_strategy`.
- Обновлены сообщения в `core/db/read_v3/partitioning/adapters.py` на терминологию `partition_grouping mode`.
- Синхронизированы benchmarking-узлы и benchmark-пайплайны: в `src/nodes/testing/read_benchmark_db_nodes.py`, `services/task_benchmarking/pipelines/benchmarks/read/sqlite/read_v3_benchmark.json` и `services/task_benchmarking/pipelines/benchmarks/read/clickhouse/read_v3_groupby.json` заменен `partition_strategy` на `partition_grouping` с `{\"mode\": \"range\"}`.
- Актуализированы тесты `read_v3`: в `tests/unit/core/db/read_v3/test_sqlite_e2e.py` конфликтный тест заменен на позитивный сценарий `partition_grouping.mode=\"hash\"`.
- Выполнены прогоны:
- `pytest tests/unit/core/db/read_v3 tests/unit/src/nodes/extract/test_read_query_from_db_v3.py tests/unit/src/nodes/extract/test_read_table_from_db_v3.py -q` (29 passed).
- `pytest tests/integration/core/db/read_v3/test_read_v3_integration.py tests/integration/src/nodes/extract/test_read_db_v3_nodes.py -q` (8 passed).
### 2026-02-18 19:00:52
- Добавлены unit-тесты для `services/gateway/routes/project/data/dataframe.py` в `tests/unit/services/gateway/routes/project/data/test_dataframe.py`: успешный сценарий `GET /projects/{project_id}/dataframe/{node_id}` с пагинацией, проверка типов колонок (`INT`, `FLOAT`, `BOOLEAN`, `STRING`, `DATETIME`), негативный сценарий отсутствия meta (`404`) и проверка `_stream_csv_partitions` (BOM + единичный заголовок CSV).
- Добавлен integration-тест `tests/integration/services/gateway/routes/project/data/test_dataframe_integration.py` с реальными `RedisCacheManager`/`RedisIndexManager`, подтверждающий корректное восстановление типов колонок сохраненного DataFrame после cache/index round-trip (`INT`, `FLOAT`, `BOOLEAN`, `STRING`, `DATETIME`, `TIMEDELTA`).
- Выполнен таргетный прогон: `pytest tests/unit/services/gateway/routes/project/data/test_dataframe.py tests/integration/services/gateway/routes/project/data/test_dataframe_integration.py` — `4 passed`.

### 2026-02-18 19:07:52
- Подготовлен и сохранен план переработки ноды `DataFrameFilter` в `tmp/df_filter_refactor_plan.md`.
- В плане зафиксирован новый целевой контракт V2: сложные логические выражения через `expression`, сравнение `column vs column` и явный `literal null`.
- Добавлены этапы внедрения для backend/UI, обновления тестов и критерии готовности с примерами payload/кода.

### 2026-02-18 19:22:14
- Переписан план `tmp/df_filter_refactor_plan.md` с учетом уточнений: вместо строкового `expression` выбран структурный рекурсивный контракт `conditions` (дерево `FilterAND`/`FilterOR`/`FilterCondition`).
- В плане добавлено решение по null-литералу: ввести общий токен `NULL_VALUE = "__dvt_null_value"` в слое `src/types` и поддерживать его как эквивалент `None`.
- В плане зафиксировано, что использование `IO.COLUMN_NAME` для `FilterOperand.type` признано нецелесообразным, чтобы не смешивать типы IO-ноды и доменную модель операндов фильтра.
### 2026-02-18 19:32:36
- Обновлен план задач в `AGENTS_TASKS.md`: добавлен пункт о создании новой миграции в `migrations/versions` для автоматического обновления данных нод со старой версии на новую с валидным `downgrade`.

### 2026-02-18 19:35:03
- Добавлены новые интеграционные тесты нод чтения V3 по всем SQL-БД из контейнерных фикстур: `tests/integration/src/nodes/extract/read_table_from_db_v3/test_read_table_from_db_v3_all_dbs.py` и `tests/integration/src/nodes/extract/read_query_from_db_v3/test_read_query_from_db_v3_all_dbs.py`.
- Добавлен общий helper `tests/integration/src/nodes/extract/read_db_v3_matrix_helpers.py` с кросс-диалектными утилитами: генерация широких nullable-данных, DDL/insert/drop для PostgreSQL/MySQL/MSSQL/Oracle/ClickHouse и общие ассерты результата чтения.
- В тестах реализованы сценарии чтения wide-таблиц с разнообразными типами (`TEXT/STRING`, `INT`, `FLOAT`, `DECIMAL`, `BOOLEAN/bit/number(1)`, `TIMESTAMP/DATETIME`, `DATE`) и nullable-значениями для каждого столбца.
- Добавлена маркировка `xfail` для MSSQL и Oracle параметров из-за известных ограничений `read_v3` bounded SQL (MSSQL: `ORDER BY` внутри derived table; Oracle: alias/обертка в capped SQL).
- Выполнены проверки: `pytest --collect-only` для новых модулей (`10 collected`), таргетный прогон `-k postgres` (`2 passed`), полный прогон новых модулей (`6 passed, 4 xfailed`).

### 2026-02-18 19:45:09
- Расширены интеграционные тесты чтения V3 строгой проверкой типов: в helper `tests/integration/src/nodes/extract/read_db_v3_matrix_helpers.py` добавлены `EXPECTED_WIDE_TYPES_BY_FAMILY`, `dataframe_type_map` и `assert_strict_wide_types`.
- Обновлены тесты `test_read_table_from_db_v3_all_dbs.py` и `test_read_query_from_db_v3_all_dbs.py`: после чтения теперь проверяется не только состав/nullable-данные, но и точное совпадение карты типов по диалекту.
- Добавлены отдельные async-тесты кэширования через `RedisCacheManager` и `RedisIndexManager`: `tests/integration/src/nodes/extract/read_table_from_db_v3/test_read_table_from_db_v3_cache_redis.py` и `tests/integration/src/nodes/extract/read_query_from_db_v3/test_read_query_from_db_v3_cache_redis.py`.
- В cache-тестах проверяются: корректное сохранение meta (`node.output._meta`), наличие и чтение всех partition-entry из индекса, восстановление полного DataFrame из кэша и строгое совпадение типов восстановленных данных.
- Выполнены проверки: `pytest --collect-only` для 4 модулей (`20 collected`), полный прогон `pytest` по этим 4 модулям (`12 passed, 8 xfailed`).
### 2026-02-18 19:36:04
- Уточнено размещение пункта про миграцию: в `tmp/df_filter_refactor_plan.md` в раздел «Порядок внедрения» добавлены шаги по созданию новой Alembic-миграции в `migrations/versions` для автообновления данных нод и по реализации валидного `downgrade`.
- В `tmp/df_filter_refactor_plan.md` в раздел «Критерии готовности» добавлено требование наличия рабочей миграции с корректными `upgrade`/`downgrade`.
- Пункт про миграцию удален из `AGENTS_TASKS.md`, чтобы не дублировать его вне целевого плана.
### 2026-02-18 19:51:17
- Выполнен backend-рефактор `DataFrameFilter` в `src/nodes/transform/df_filter.py`: введен контракт `conditions` (дерево `condition/and/or`), удалены старые входы `filter_conditions` и `logic`, реализован рекурсивный evaluator и поддержка `column vs column` для сравнений.
- Добавлен общий null-токен `NULL_VALUE` в `src/types/constants.py` и экспорт в `src/types/__init__.py`; в фильтре реализована нормализация `None` и `NULL_VALUE` как literal-null.
- Обновлена семантика операций: `==/!=` с null-литералом, запрет `>, <, >=, <=` с null-литералом, валидация групп/операндов через `TypeAdapter(FilterNode)`.
- Обновлены тесты фильтра: полностью переписан `tests/unit/src/nodes/transform/test_df_filter.py` под новый контракт (`nested AND/OR`, `column vs column`, null-литералы, ошибки валидации, `output/inverted_output`).
- Обновлены pipeline-шаблоны и интеграционные тесты: `tests/unit/src/pipeline/templates/df_filter.py` (новый helper `build_condition`, вход `conditions`) и `tests/integration/src/pipeline/test_processor.py`.
- Добавлена миграция `migrations/versions/0027_migrate_df_filter_inputs_to_conditions_tree.py` для автоматической конвертации данных нод `DataFrameFilter` из legacy-формата (`filter_conditions` + `logic`) в `conditions` и обратно в `downgrade`.
- Добавлены unit-тесты миграции: `tests/unit/migrations/versions/test_0027_migrate_df_filter_inputs_to_conditions_tree.py` (проверка upgrade, downgrade и round-trip для пустых условий).
- Выполнены прогоны:
- `pytest tests/unit/src/nodes/transform/test_df_filter.py tests/unit/migrations/versions/test_0027_migrate_df_filter_inputs_to_conditions_tree.py` (`16 passed`).
- `pytest tests/integration/src/pipeline/test_processor.py::test_pipeline_with_select_and_filter tests/integration/src/pipeline/test_processor.py::test_pipeline_s3_load_csv_db_filters_join` (`2 passed`).
### 2026-02-19 12:38:37
- Исправлена деградация типов в `core/db/read_v3/executors/sql.py`: `build_meta()` теперь строит `meta` по sample-выборке (`cap_rows_sql(..., 1)` + `head(0)`), а не только через `WHERE 1=0`; это сохраняет реальные dtype колонок и предотвращает превращение всех полей в `string` в `Dask._meta`.
- Добавлен fallback в `build_meta()` на `SELECT ... WHERE 1=0` для случая пустого источника данных.
- Удален временный отладочный вывод из `src/nodes/extract/read_table_from_db_v3.py`.
- Добавлен unit-тест регрессии `tests/unit/core/db/read_v3/test_executor_sql.py::test_build_meta_uses_sample_row_dtypes`, проверяющий, что `build_meta()` берет dtype из sample-rows и не уходит в ветку `WHERE 1=0` при наличии данных.
- Добавлены unit-тесты нод `ReadTableFromDBV3` и `ReadQueryFromDBV3` (`tests/unit/src/nodes/extract/test_read_table_from_db_v3.py`, `tests/unit/src/nodes/extract/test_read_query_from_db_v3.py`) с проверкой, что ключевые колонки в `output._meta` не имеют `string` dtype.
- Выполнен таргетный прогон: `pytest tests/unit/core/db/read_v3/test_executor_sql.py tests/unit/src/nodes/extract/test_read_table_from_db_v3.py tests/unit/src/nodes/extract/test_read_query_from_db_v3.py` — `8 passed`.
### 2026-02-19 12:43:15
- Добавлены интеграционные проверки `meta`-типов для read_v3 нод по матрице всех SQL-БД (PostgreSQL, MySQL, ClickHouse, MSSQL, Oracle) в `tests/integration/src/nodes/extract/read_table_from_db_v3/test_read_table_from_db_v3_all_dbs.py` и `tests/integration/src/nodes/extract/read_query_from_db_v3/test_read_query_from_db_v3_all_dbs.py`.
- В `tests/integration/src/nodes/extract/read_db_v3_matrix_helpers.py` добавлен helper `assert_wide_meta_non_string_types`, который проверяет, что колонки, ожидаемые как нестроковые, не деградируют в `DataType.STRING` в `node.output._meta`.
- Таргетно выполнен прогон: `pytest tests/integration/src/nodes/extract/read_table_from_db_v3/test_read_table_from_db_v3_all_dbs.py tests/integration/src/nodes/extract/read_query_from_db_v3/test_read_query_from_db_v3_all_dbs.py` — результат `6 passed, 4 xfailed` (xfail для MSSQL/Oracle соответствует известным ограничениям read_v3).
### 2026-02-19 12:50:38
- Исправлена обработка пустых источников в `read_v3`, чтобы типы колонок в `Dask._meta` не деградировали в `STRING` при чтении пустых таблиц/запросов.
- В `core/db/read_v3/models.py` расширен `ReadV3Plan`: добавлено поле `output_column_kinds` с type-hints по выходным колонкам.
- В `core/db/read_v3/planner/table.py` добавлено заполнение `output_column_kinds` на основе introspection `inspector.get_columns(...)` и `dialect.detect_value_kind(...)`.
- В `core/db/read_v3/planner/query.py` добавлено best-effort определение типов колонок запроса через диалектные describe-пути (`ClickHouse DESCRIBE`, `Postgres pg_type + cursor.description`, `MSSQL sys.types`, `Oracle cursor.description`, `MySQL type codes`), плюс нормализация mysql-кодов (`LONG/TINY/NEWDECIMAL/...`) в SQL-подобные имена.
- В `core/db/read_v3/executors/sql.py` добавлено применение type-hints для empty-partitions и fallback-ветки `build_meta()` (`WHERE 1=0`), включая явные dtype для numeric/bool/datetime.
- Добавлены отдельные интеграционные тесты пустых таблиц по всем SQL-БД:
  - `tests/integration/src/nodes/extract/read_table_from_db_v3/test_read_table_from_db_v3_empty_all_dbs.py`
  - `tests/integration/src/nodes/extract/read_query_from_db_v3/test_read_query_from_db_v3_empty_all_dbs.py`
- В `tests/integration/src/nodes/extract/read_db_v3_matrix_helpers.py` добавлен helper `seed_empty_wide_table(...)` и расширена проверка `assert_wide_meta_non_string_types(...)` для `node.output._meta`.
- Выполнены прогоны:
  - `pytest tests/unit/core/db/read_v3 tests/unit/src/nodes/extract/test_read_table_from_db_v3.py tests/unit/src/nodes/extract/test_read_query_from_db_v3.py` (`32 passed`).
  - `pytest tests/integration/src/nodes/extract/read_table_from_db_v3/test_read_table_from_db_v3_all_dbs.py tests/integration/src/nodes/extract/read_query_from_db_v3/test_read_query_from_db_v3_all_dbs.py tests/integration/src/nodes/extract/read_table_from_db_v3/test_read_table_from_db_v3_empty_all_dbs.py tests/integration/src/nodes/extract/read_query_from_db_v3/test_read_query_from_db_v3_empty_all_dbs.py` (`12 passed, 8 xfailed`).
### 2026-02-19 13:08:53
- Исправлено дублирование индекса в метаданных DataFrame: в `core/metadata/df_metadata.py` при совпадении имени индекса и имени колонки больше не создаются две записи `Column` с одинаковым `name`; существующая колонка помечается `index=True`.
- Для `read_v3` добавлена более точная типизация пустых результатов по колонкам и индексу:
  - `ReadV3Plan` расширен полями `partition_key_type_repr` и `output_column_type_repr` (`core/db/read_v3/models.py`).
  - В planner’ах (`core/db/read_v3/planner/table.py`, `core/db/read_v3/planner/query.py`) добавлено заполнение type-repr карт по колонкам.
  - В SQL executor (`core/db/read_v3/executors/sql.py`) типы для empty `meta`/partition теперь вычисляются с учетом type-repr (включая integer-распознавание для `int/bigint/serial/number(...,0)`), а dtype индекса задается явно (чтобы не получать `object/string`).
- В `core/db/read_v3/planner/query.py` улучшена нормализация MySQL type-code имен (`LONG/LONGLONG/SHORT/TINY/NEWDECIMAL/...`) для корректного определения `ValueKind` на пустых query-результатах.
- Удален временный отладочный вывод из `src/nodes/extract/read_table_from_db_v3.py`.
- Добавлен unit-регрессионный тест `tests/unit/core/metadata/test_df_metadata.py::test_get_df_metadata_merges_named_index_with_same_column_name`.
- Расширен интеграционный тест пустых таблиц `tests/integration/src/nodes/extract/read_table_from_db_v3/test_read_table_from_db_v3_empty_all_dbs.py`: теперь дополнительно проверяется `infer_metadata()` (одна колонка `id`, `index=True`, `dtype=INT`, без дублей имен колонок).
- Выполнены прогоны:
  - `pytest tests/unit/core/metadata/test_df_metadata.py tests/unit/core/db/read_v3 tests/unit/src/nodes/extract/test_read_table_from_db_v3.py tests/unit/src/nodes/extract/test_read_query_from_db_v3.py` (`37 passed`).
  - `pytest tests/integration/src/nodes/extract/read_table_from_db_v3/test_read_table_from_db_v3_all_dbs.py tests/integration/src/nodes/extract/read_query_from_db_v3/test_read_query_from_db_v3_all_dbs.py tests/integration/src/nodes/extract/read_table_from_db_v3/test_read_table_from_db_v3_empty_all_dbs.py tests/integration/src/nodes/extract/read_query_from_db_v3/test_read_query_from_db_v3_empty_all_dbs.py` (`12 passed, 8 xfailed`).
### 2026-02-19 13:35:28
- Исправлена нода `DataFrameCastColumnType` (`src/nodes/transform/df_cast_column_type.py`): для datetime-кастов добавлена безопасная нормализация через `dd.to_datetime(..., utc=True)` с поддержкой `datetime64[ns]` и `datetime64[ns, <tz>]`, что устраняет падение на смешанных tz-aware/tz-naive значениях.
- Сохранено стандартное поведение `astype` для не-datetime колонок, при этом касты datetime выполняются отдельно перед общим приведением типов.
- Добавлены регрессионные unit-тесты `tests/unit/src/nodes/transform/test_df_cast_column_type.py` для кейса смешанных timezone-значений в колонке `Period` и комбинированного каста datetime + float.
- Выполнен таргетный прогон: `pytest tests/unit/src/nodes/transform/test_df_cast_column_type.py` (`2 passed`).

### 2026-02-19 13:35:59
- В `AGENTS_TIPS.md` добавлена заметка по обработке mixed `tz-aware`/`tz-naive` в `DataFrameCastColumnType` (безопасный паттерн через `dd.to_datetime(..., utc=True)` и последующую нормализацию).
### 2026-02-19 14:06:01
- Исправлена сериализация pandas DataFrame в `core/dump_engine/_pandas.py`: добавлен fallback для `object`-колонок со смешанными `Decimal` и `float/int` (нормализация в числовой тип перед `pa.Table.from_pandas`).
- Реализована выборочная логика: нормализация применяется только к колонкам вида `Decimal + numeric`, чтобы не затрагивать прочие `object`-данные.
- Добавлен регрессионный тест `tests/unit/core/dump_engine/test_pandas.py::test_dump_handles_mixed_decimal_and_float_in_object_column` для кейса, аналогичного падению по `ValPrib`.
- Выполнены проверки:
  - `pytest tests/unit/core/dump_engine/test_pandas.py` (`51 passed`).
  - `pytest tests/unit/core/dump_engine/test_dump_load.py` (`16 passed`).
- В `AGENTS_TIPS.md` добавлена заметка по паттерну обработки mixed `Decimal/float` в `object`-колонках при PyArrow-сериализации.
### 2026-02-19 14:27:07
- Исправлена нода `DataFrameUnion` (`src/nodes/transform/df_union.py`): добавлена нормализация общих datetime-колонок перед `dd.concat`, чтобы избежать деградации типа в `object/string` при смешении `tz-aware` и `tz-naive` данных.
- Добавлены helper-методы `_is_datetime_dtype`, `_cast_datetime_series_to_ns_naive`, `_normalize_common_datetime_columns`; унификация выполняется через `dd.to_datetime(..., utc=True)` с приведением к `datetime64[ns]`.
- Сохранена безопасная семантика: нормализация применяется только когда обе стороны колонки datetime-like; кейсы `datetime + string` не форсируются в datetime.
- Добавлен расширенный набор unit-тестов `tests/unit/src/nodes/transform/test_df_union_dtypes.py` (17 сценариев): datetime precision (`ns/us`), разные таймзоны, naive vs tz-aware, mapping, multi-partitions и смешанные типы (`Int64/int`, `float32/float64`, `boolean/bool`, `category`, `timedelta`, `Decimal+float`, `string/object`).
- Выполнены проверки:
  - `pytest tests/unit/src/nodes/transform/test_df_union.py tests/unit/src/nodes/transform/test_df_union_dtypes.py` (`25 passed`).
  - `pytest tests/unit/src/nodes/transform` (`66 passed`).
### 2026-02-19 14:34:59
- Исправлена нода `WriteDataFrameToDB` (`src/nodes/write/write_df_to_db.py`) для сценария ClickHouse с `create_table_sql` и режимом `recreate`: вместо `table.metadata.create_all(...)` теперь используется явное создание таблицы через SQL и последующий `autoload`.
- Добавлены helper-методы `_extract_create_table_sql_table_name` и `_execute_create_table_sql_and_reflect`; логика SQL-создания также применена в `append/truncate`, если таблица отсутствует и задан `create_table_sql`.
- Исправление устраняет падение `sqlalchemy.exc.CompileError: No engine for table 'ProjectValPrib'` при пересоздании таблицы из `create_table_sql`.
- Добавлены unit-тесты в `tests/unit/src/nodes/test_nodes_runtime.py`:
  - `test_write_dataframe_to_db_recreate_with_create_table_sql_uses_sql_recreate`;
  - `test_write_dataframe_to_db_append_with_create_table_sql_creates_via_sql_when_missing`.
- Выполнен прогон: `pytest tests/unit/src/nodes/test_nodes_runtime.py` (`5 passed`).
- В `AGENTS_TIPS.md` добавлена заметка по паттерну `recreate + create_table_sql` для ClickHouse.
### 2026-02-19 14:44:13
- Исправлена сериализация datetime для ClickHouse-вставки в `core/db/write_v2/clickhouse.py`: добавлена нормализация `_normalize_clickhouse_datetime_value` с учетом типа колонки (`DateTime` vs `DateTime64`).
- Для `DateTime` введена проверка диапазона (`1970-01-01 .. 2106-02-07 06:28:15`); значения вне диапазона преобразуются в `None`, что предотвращает падения драйвера при `timestamp()` на Windows.
- Для `DateTime64` добавлено приведение к timezone-aware UTC `datetime`, чтобы избежать `OSError: [Errno 22] Invalid argument` на pre-epoch значениях.
- Синхронизирована аналогичная логика в `core/db/clickhouse_insert.py`, чтобы не было расхождения между реализациями вставки.
- Добавлены unit-тесты `tests/unit/core/db/write_v2/test_clickhouse.py`:
  - `test_prepare_column_data_datetime_out_of_range_for_datetime_becomes_none`;
  - `test_prepare_column_data_datetime64_pre_epoch_is_converted_to_aware_utc`.
- Выполнен прогон: `pytest tests/unit/core/db/write_v2/test_clickhouse.py` (`4 passed`).
- В `AGENTS_TIPS.md` добавлена заметка по обработке pre-epoch datetime для ClickHouse на Windows.
### 2026-02-19 14:48:57
- Уточнен фикс сериализации datetime для ClickHouse: в `core/db/write_v2/clickhouse.py` и `core/db/clickhouse_insert.py` для `DateTime` теперь передается timezone-aware UTC `datetime` (а не naive), так как `clickhouse_connect` вызывает `timestamp()` и naive-значения на Windows продолжают падать с `OSError: [Errno 22] Invalid argument`.
- Сохранен range-check для `DateTime` (`1970-01-01 .. 2106-02-07 06:28:15`), out-of-range значения остаются `None`.
- Обновлен unit-тест `tests/unit/core/db/write_v2/test_clickhouse.py::test_prepare_column_data_datetime_out_of_range_for_datetime_becomes_none` под новый ожидаемый формат (UTC-aware datetime для валидного значения).
- Выполнен прогон: `pytest tests/unit/core/db/write_v2/test_clickhouse.py` (`4 passed`).
- В `AGENTS_TIPS.md` добавлена заметка о необходимости передавать UTC-aware datetime для ClickHouse `DateTime` на Windows.
### 2026-02-19 16:22:43
- Добавлена новая Alembic-миграция `migrations/versions/0028_rename_graph_input_handles.py`.
- В `upgrade` реализовано обновление `graph_edges.target_handle`: `input-dataframe` -> `input-df`, `include_index` -> `index`, `include_header` -> `header`.
- В `upgrade` реализовано обновление JSONB-ключей в `graph_nodes.input_values`: `dataframe` -> `df`, `include_index` -> `index`, `include_header` -> `header` с сохранением значений.
- Добавлен обратный `downgrade` для обоих преобразований (`graph_edges` и `graph_nodes.input_values`).
### 2026-02-19 17:21:31
- Обновлены тестовые шаблоны пайплайнов под рефакторинг `InputField` без `name`: в `tests/unit/src/pipeline/templates/df_drop_columns.py`, `tests/unit/src/pipeline/templates/df_exec_code.py`, `tests/unit/src/pipeline/templates/df_filter.py`, `tests/unit/src/pipeline/templates/df_select_columns.py` и `tests/unit/src/pipeline/templates/save_excel.py` вход `dataframe` заменен на `df` для нод, где ожидается `df`.
- Исправлен integration-кейс `SaveCSV` в `tests/integration/src/pipeline/test_processor.py`: ключ входа `dataframe` заменен на `df`.
- В `AGENTS_TIPS.md` добавлена заметка по типовой регрессии после удаления `InputField.name` (`dataframe` vs `df`) и правилу сверки по `attr_name`.
- Выполнены проверки:
  - `pytest tests/integration/src/pipeline/test_processor.py -q` (`7 passed`).
  - `pytest tests/unit tests/integration -q` (`648 passed, 12 xfailed`).
### 2026-02-19 18:26:41
- В `core/db/read_v3/executors/sql.py` исправлена нормализация datetime-колонок по type-hints: добавлен безопасный путь для mixed `tz-aware`/`tz-naive` через `pd.to_datetime(..., utc=True)` с приведением к целевому dtype.
- Нормализация datetime теперь применяется не только к fallback `meta` (`WHERE 1=0`), но и к `meta` из sample-строки (`head(0)`), а также к непустым партициям в `load_partition`.
- Это устраняет падение выражений в transform-нодах при сравнении дат с разной timezone-природой (`Cannot compare tz-naive and tz-aware datetime-like objects`).
- Добавлены регрессионные unit-тесты в `tests/unit/core/db/read_v3/test_executor_sql.py`:
  - `test_build_meta_normalizes_mixed_datetime_tz`;
  - `test_load_partition_normalizes_mixed_datetime_tz`.
- Выполнен таргетный прогон: `pytest tests/unit/core/db/read_v3/test_executor_sql.py -q` (`6 passed`).
### 2026-02-19 18:40:41
- В ноде `SaveParquet` (`src/nodes/write/save_parquet.py`) реализован `row-cap` режим через новый инпут `row_cap` (максимум строк в одном parquet-файле) с жестким разбиением dask-партиций на чанки `<= row_cap`.
- В `SaveParquet` добавлен жесткий контракт parquet-типов через инпут `parquet_types` (`{column_name: parquet_type}`) и парсер в `pyarrow.DataType` (поддержка алиасов, `timestamp[...]`, `time32/time64[...]`, `decimal128/256(...)`); контракт пробрасывается в `to_parquet(schema=...)`.
- В `SaveParquet` исправлена нормализация имени файла: удаление суффикса `.parquet` теперь выполняется корректно (без побочного обрезания символов через `rstrip`).
- Обновлен UI-редактор `SaveParquet` (`services/ui/src/node-extensions/saveParquet/ui/SaveParquetEditor.tsx`): добавлены инпут `row_cap` и выбор parquet-типа по каждой колонке входного DataFrame с валидацией.
- Добавлены unit-тесты `tests/unit/src/nodes/write/test_save_parquet.py` (row-cap + schema-contract, включая негативные сценарии).
- Выполнен прогон: `pytest tests/unit/src/nodes/write/test_save_parquet.py` (`4 passed`).
### 2026-02-19 19:25:19
- Обновлены ожидания типов в `tests/integration/src/nodes/extract/read_db_v3_matrix_helpers.py` для Postgres/MySQL/ClickHouse в соответствии с текущим контрактом `read_v3` (int/bool/date dtype).
- Исправлен шаблон пайплайна `tests/unit/src/pipeline/templates/write_df_to_db.py`: вход `dataframe` переименован в `df` для `WriteDataFrameToDB`.
- Актуализированы integration-тесты `tests/integration/src/pipeline/test_processor.py`: чтение результата из `DataFrameDisplayNode.dataframe` вместо удаленного атрибута `df`.
- Выполнен полный прогон `pytest tests/integration`: `93 passed, 12 xfailed`.

### 2026-02-20 10:55:33
- Добавлена поддержка `mssql` и `oracle` в `core/db/read_v3` без `xfail`-ограничений в matrix-интеграционных тестах.
- В `core/db/read_v3/dialects/mssql.py` доработан `cap_rows_sql`: добавлена безопасная обработка CTE (`WITH ...`) через инъекцию `TOP (N)` в внешний `SELECT`, а также добавление `OFFSET 0 ROWS` для `ORDER BY` внутри derived-table.
- В `core/db/read_v3/dialects/oracle.py` добавлен override `cap_rows_sql` с валидным для Oracle alias `dvt_cap` (вместо alias, начинающегося с `_`).
- В `core/db/read_v3/planner/query.py` расширена нормализация type-hints для `mssql/oracle` по `cursor.description` (учет `precision/scale`, маппинг Python/DB type-code в SQL-имена), что устранило деградацию `meta` в `STRING` на пустых query-результатах.
- В `core/db/read_v3/planner/table.py` добавлена нормализация type-repr числовых колонок по `precision/scale` для стабильного integer-dtype контракта (в т.ч. для Oracle `NUMBER`).
- Обновлены unit-тесты `tests/unit/core/db/read_v3/test_executor_sql.py`: скорректирован кейс MSSQL bounded SQL и добавлены проверки для MSSQL CTE/Oracle alias.
- Обновлены интеграционные ожидания в `tests/integration/src/nodes/extract/read_db_v3_matrix_helpers.py` и проверка `id` metadata-типа в `tests/integration/src/nodes/extract/read_table_from_db_v3/test_read_table_from_db_v3_empty_all_dbs.py` под актуальный кросс-БД контракт.
- Выполнены проверки:
  - `pytest tests/unit/core/db/read_v3 -q` (`32 passed`);
  - `pytest tests/unit/src/nodes/extract/test_read_table_from_db_v3.py tests/unit/src/nodes/extract/test_read_query_from_db_v3.py -q` (`4 passed`);
  - `pytest tests/integration/src/nodes/extract/read_table_from_db_v3/test_read_table_from_db_v3_all_dbs.py tests/integration/src/nodes/extract/read_query_from_db_v3/test_read_query_from_db_v3_all_dbs.py tests/integration/src/nodes/extract/read_table_from_db_v3/test_read_table_from_db_v3_empty_all_dbs.py tests/integration/src/nodes/extract/read_query_from_db_v3/test_read_query_from_db_v3_empty_all_dbs.py -q` (`20 passed`).

### 2026-02-20 11:46:23
- Добавлен integration-тест `tests/integration/services/gateway/routes/test_db_connections.py` для маршрутов `services/gateway/routes/db_connections.py`.
- Реализована параметризация по всем типам подключений из контейнерных фикстур: `postgres`, `clickhouse`, `mysql`, `mongodb`, `mssql`, `kafka`, `s3`, `oracle`.
- В тесте покрыт сценарий `create -> list(connection_type) -> get -> check -> check by id -> delete -> get(404)` для каждого типа.
- Для S3 (MinIO) добавлена подготовка bucket перед проверкой подключения.
- Добавлен локальный тестовый patch `sqlalchemy.orm.Session.exec` (через `monkeypatch`) для совместимости `db_connection`-роутов с текущей integration-фикстурой `gateway_client`.
- Выполнен прогон: `pytest tests/integration/services/gateway/routes/test_db_connections.py -q` (`8 passed`).

### 2026-02-20 12:04:18
- Выполнено практическое сравнение запуска Python через `.venv3.13/Scripts/python.exe` и через инструмент `mcp_python_interpreter` (базовый запуск, импорт модулей проекта, сохранение состояния между вызовами, запуск файла с аргументами).
- Зафиксировано, что `mcp_python_interpreter` в режиме `inline` в этой среде использует системный Python `3.14.2` (`C:\Users\sadzip\AppData\Local\Python\pythoncore-3.14-64\python.exe`), тогда как прямой вызов использует проектный `.venv3.13` (`3.13.11`).
- Зафиксированы ограничения `mcp_python_interpreter` в текущей Windows-среде: `run_python_code` в режиме `subprocess` и `run_python_file` завершаются с ошибкой `Errno 22 Invalid argument`.
- Для проверки `run_python_file` создавался и был удален временный файл `tmp/python_compare_probe.py`.

### 2026-02-20 12:07:18
- В `AGENTS_TIPS.md` добавлена заметка `Python CLI vs mcp_python_interpreter` с практическими рекомендациями: когда использовать `.venv3.13/Scripts/python.exe`, какие ограничения есть у `mcp_python_interpreter` в текущей Windows-среде, и почему инструкции лучше давать через обычный Python CLI.
- Явно добавлено примечание о переносимости: у другого пользователя/агента инструмента `mcp_python_interpreter` может не быть.

### 2026-02-20 12:24:33
- Добавлен новый FastMCP-сервис `dvt_mcp` в `services/dvt_mcp` (`main.py`, `runtime.py`, `README.md`, `__init__.py`) с набором инструментов для работы с Python в проекте: `run_python_code` (`inline`/`subprocess`), `run_python_file`, управление inline-сессиями и project-tools (`run_pytest`, `run_ruff_check`, `run_gen_protos`).
- Реализована загрузка `.env` из корня проекта при старте сервиса (`services/dvt_mcp/runtime.py::load_project_env`).
- Реализован резолв интерпретатора по требуемому алгоритму: приоритет `DVT_VENV_PATH`, затем обход директорий верхнего уровня проекта по шаблону `{dir}/Scripts/python.exe` с проверкой версии против `pyproject.toml:[project].requires-python`, затем fallback на `sys.executable`.
- Добавлен entrypoint `scripts/run_dvt_mcp.py` с аргументами `--transport` и `--no-reexec`; по умолчанию предусмотрен перезапуск процесса на резолвленный проектный интерпретатор.
- Обновлены зависимости: в `requirements.txt` добавлен `mcp==1.26.0`.
- Добавлены unit-тесты `tests/unit/services/dvt_mcp/test_runtime.py` для проверки загрузки `.env`, matching `requires-python`, сканирования интерпретатора и приоритета `DVT_VENV_PATH`.
- Выполнены проверки:
  - `pytest tests/unit/services/dvt_mcp -q` (`4 passed`);
  - `python -m scripts.services.run_dvt_mcp --no-reexec --help` (успешный запуск CLI-help).
- Проверка `ruff` не выполнена в текущем venv: `No module named ruff`.

### 2026-02-20 13:19:04
- Обновлен файл `.codex/config.toml`: зарегистрирован MCP-сервер `dvt_mcp`.
- Для `dvt_mcp` добавлен запуск через `C:\work\projects\Visual_transformer\.venv3.13\Scripts\python.exe -m scripts.services.run_dvt_mcp`.
- Сохранена существующая регистрация `mcp_python_interpreter`.

### 2026-02-20 14:23:39
- Обновлен `.codex/config.toml` для `dvt_mcp`: фиксированный путь к `.venv3.13\Scripts\python.exe` заменен на универсальный запуск через `python -m scripts.services.run_dvt_mcp`, чтобы не зависеть от имени/пути локального venv у разных пользователей.
- В `scripts/run_dvt_mcp.py` добавлена явная проверка минимальной версии интерпретатора (`Python >= 3.10`) с понятным сообщением об ошибке при запуске на более старой версии.
- Выполнены проверки: TOML-валидация `.codex/config.toml` и запуск `python -m scripts.services.run_dvt_mcp --help`.

### 2026-02-20 14:31:50
- Проведена проверка доступности и работы `dvt_mcp`: инструменты `get_runtime_info` и `run_python_code` (`inline`) доступны и возвращают корректные данные проектного интерпретатора.
- Выявлена проблема таймаута для `run_python_code` (`subprocess`) и `run_python_file` в `stdio`-режиме MCP при запуске дочернего Python-процесса.
- В `services/dvt_mcp/main.py::_run_command` добавлен фикс `stdin=subprocess.DEVNULL`, чтобы дочерние процессы не наследовали `stdin` MCP и не зависали.
- Добавлен unit-тест `tests/unit/services/dvt_mcp/test_main.py::test_run_command_uses_devnull_stdin`.
- Выполнен прогон `pytest tests/unit/services/dvt_mcp -q` (`5 passed`).
- В `AGENTS_TIPS.md` добавлена заметка про timeout дочернего Python в `FastMCP` (`stdio`) и способ фикса.

### 2026-02-20 14:34:14
- В `AGENTS.md` добавлен новый раздел `Project MCP Tool (dvt_mcp)` с описанием назначения и возможностей инструмента `dvt_mcp`.
- Зафиксировано правило приоритета: при наличии эквивалентных возможностей использовать tools `dvt_mcp` вместо неудобных shell-команд.
- Добавлено требование расширять `services/dvt_mcp` новыми tools при выявлении повторяющихся неудобств в работе.
- Добавлено требование поддерживать раздел `dvt_mcp` в `AGENTS.md` в актуальном состоянии при любых изменениях `services/dvt_mcp`.
- Добавлено правило диагностики недоступности инструмента `dvt_mcp` с запросом конкретных действий у пользователя при необходимости (перезапуск сессии, проверка конфигурации/зависимостей, предоставление ошибок запуска).

### 2026-02-20 14:55:26
- В `services/dvt_mcp/main.py` обновлен контракт `_run_command`: параметр `timeout_sec` сделан опциональным (`int | None`), чтобы поддерживать запуск команд без лимита времени.
- Для инструмента `run_pytest` в `services/dvt_mcp/main.py` убран обязательный timeout по умолчанию: `timeout_sec` теперь `None`, что позволяет запускать долгие интеграционные тесты без принудительного прерывания.
- Добавлен unit-тест `tests/unit/services/dvt_mcp/test_main.py::test_run_pytest_without_timeout_by_default`, проверяющий, что `run_pytest` передает `timeout_sec=None` в `_run_command`.
- Обновлен блок `Project MCP Tool (dvt_mcp)` в `AGENTS.md`: добавлено уточнение, что `run_pytest` поддерживает опциональный `timeout_sec` и по умолчанию выполняется без timeout.
- Выполнены проверки через `dvt_mcp.run_pytest`:
  - `tests/unit/services/dvt_mcp/test_main.py -q` (`2 passed`);
  - `tests/unit/services/dvt_mcp -q` (`6 passed`).

### 2026-02-20 14:59:58
- Для `dvt_mcp` реализован hot reload логики инструментов без перезапуска сессии: добавлен модуль `services/dvt_mcp/operations.py`, в который вынесены реализации tool-операций.
- В `services/dvt_mcp/main.py` добавлен диспетчер с авто-перезагрузкой `services.dvt_mcp.operations` по изменению файла (управляется `DVT_MCP_HOT_RELOAD`, по умолчанию `true`).
- Инструменты `dvt_mcp` в `main.py` переведены на делегирование в `operations.py`; в `get_runtime_info` добавлен блок `hot_reload` со статусом механизма и последней ошибкой reload.
- Уточнено поведение timeout: `run_pytest` остается без таймаута по умолчанию (`timeout_sec=None`) и передается в общий executor команд.
- Обновлены тесты:
  - добавлен `tests/unit/services/dvt_mcp/test_operations.py` (проверки `stdin=DEVNULL` и default timeout для `run_pytest`);
  - обновлен `tests/unit/services/dvt_mcp/test_main.py` (проверка делегирования `run_pytest` в operations-модуль).
- Обновлен раздел `Project MCP Tool (dvt_mcp)` в `AGENTS.md`: добавлено описание hot reload и ограничение, что добавление/удаление tool-деклараций в `main.py` требует перезапуска MCP-сессии.
- Выполнена проверка: `dvt_mcp.run_pytest tests/unit/services/dvt_mcp -q` (`7 passed`).

### 2026-02-20 15:04:50
- В `services/dvt_mcp` добавлен helper `append_changelog_entry`, который автоматически формирует timestamp и дописывает запись в `AGENTS_CHANGELOGS.md` без ручного редактирования файла.
- В `services/dvt_mcp/main.py` зарегистрирован новый tool `append_changelog_entry` для вызова этой функции через MCP.
- В `AGENTS.md` обновлен раздел changelog: теперь требуется вызывать функцию `dvt_mcp.append_changelog_entry` вместо ручной правки файла.
- Добавлены тесты `tests/unit/services/dvt_mcp/test_operations.py` и `tests/unit/services/dvt_mcp/test_main.py`; выполнен прогон `tests/unit/services/dvt_mcp -q` (`10 passed`).

### 2026-02-20 15:24:29
- Исправлено сохранение traceback в лог-синках: `src/logger/formatters.py` больше не затирает `extra.traceback_str`, если traceback уже передан из subprocess/multiprocessing.
- Доработан graceful shutdown `services/task_worker/celery_app.py`: закрытие и удаление DB sink теперь выполняется по актуальным значениям из `src.logger.db_sink`, что предотвращает потерю финальных логов при остановке воркера.
- Добавлены unit-тесты `tests/unit/src/logger/test_formatters.py` и `tests/unit/services/task_worker/test_celery_app.py`.
- Добавлен integration-тест `tests/integration/services/task_worker/test_db_logging.py`, проверяющий запись INFO/ERROR логов воркера в Postgres и корректное заполнение `exception_traceback` для обычных и subprocess-ошибок.

### 2026-02-20 15:42:11
- В `src/models/db_log.py` поле `task_id` обновлено: добавлен внешний ключ `tasks.task_id` (опционально).
- Добавлена alembic-миграция `migrations/versions/0029_add_logs_task_fk.py`: очистка orphan `task_id` в `logs` и создание FK `logs_task_id_fkey` на `tasks.task_id`.
- Доработан `task_worker` для явной передачи `task_id` в логи: `handle_task_control` теперь логирует через `logger.bind(task_id=...)`, а `SubprocessRunner` биндет `task_id`/`user_id`/`project_id` для success/error событий по задаче.
- Обновлены тесты: добавлен unit-тест на bind `task_id` в control-логах и адаптирован integration-тест логирования в Postgres под наличие FK на `tasks`.

### 2026-02-20 15:51:52
- В `services/dvt_mcp` добавлен новый инструмент `get_logs` для выборки логов из БД с опциональными фильтрами: `created_at` (операторы `>`, `<`, `>=`, `<=`, `==`, а также алиасы `=>` и `=<`), `level`, `service_name`, `message`/`exception_traceback` (по вхождению), `user_id`, `task_id`, `project_id` (через join `logs` -> `tasks`), `module`, `function`, `line`.
- Результат `get_logs` сортируется по `created_at` (по умолчанию `desc`, доступен `asc`), поддерживает пагинацию `limit/offset`, возвращает `project_id` и общее количество записей `total`.
- Инструмент зарегистрирован в `services/dvt_mcp/main.py` и проксируется в `services/dvt_mcp/operations.py`.
- Добавлены unit-тесты для `dvt_mcp`: делегирование `get_logs` в `test_main.py` и проверка фильтров/операторов/сортировки/валидации в `test_operations.py`.
- Обновлена документация: блок `dvt_mcp` в `AGENTS.md` и `services/dvt_mcp/README.md`.

### 2026-02-20 15:53:17
- Уточнена документация по `dvt_mcp`: из описания возможностей в `AGENTS.md` и `services/dvt_mcp/README.md` убран `run_ruff_check`, так как этот инструмент не зарегистрирован в текущем `services/dvt_mcp/main.py`.
- Список возможностей синхронизирован с фактическими MCP tools (`get_runtime_info`, `run_python_code`, `run_python_file`, `list_inline_sessions`, `clear_inline_session`, `run_pytest`, `run_gen_protos`, `append_changelog_entry`, `get_logs`).

### 2026-02-20 17:26:38
- В `services/dvt_mcp` добавлены новые инструменты: `get_projects`, `get_tasks`, `run_task`.
- `get_projects` реализует удобные фильтры по полям `projects` (id/user/name/is_deleted/store_enabled/ttl/workers, фильтры по `created_at`/`updated_at` с операторами `>`, `<`, `>=`, `<=`, `==`, `=>`, `=<`), сортировку и пагинацию.
- `get_tasks` реализует удобные фильтры по полям `tasks` (task/user/project/status/status_in/mode/force_exec/assigned_worker_id/message, фильтры по `queued_at`/`updated_at` с операторами), join с `projects` для возврата `project_name`, сортировку и пагинацию.
- `run_task` запускает задачу через существующую инфраструктуру `enqueue_task_from_project` от пользователя `config.SECURITY.DEFAULT_EMAIL` с поддержкой параметров `mode`, `force_exec`, `final_node_id`, `send_ws_messages`.
- Инструменты зарегистрированы в `services/dvt_mcp/main.py`, добавлены unit-тесты в `tests/unit/services/dvt_mcp/test_main.py` и `tests/unit/services/dvt_mcp/test_operations.py`, обновлена документация в `AGENTS.md` и `services/dvt_mcp/README.md`.

### 2026-02-20 17:35:15
- Исправлено формирование SQL-литералов даты/времени для MSSQL в `core/db/read_v3/dialects/mssql.py`: для `datetime` теперь используется `CAST(... AS DATETIME2(6))`, для `date` — `CAST(... AS DATE)`, чтобы исключить ошибки преобразования даты/времени в диапазонных предикатах.
- Добавлены регрессионные unit-тесты `tests/unit/core/db/read_v3/test_mssql_dialect.py`, проверяющие корректный рендер литералов и построение SQL-предиката диапазона в `V3GroupingHelper` для сценария с `created_at`.
нные 

### 2026-02-20 17:39:15
- Добавлены интеграционные тесты `tests/integration/core/db/read_v3/test_read_v3_mssql_integration.py` для MSSQL-сценариев с `created_at` типа `DATETIME` и `partition_grouping`.
- Покрыты оба режима `read_v3`: `table` (granularity/hour) и `query` (ranges), с проверкой успешного чтения всех строк и корректного формирования предикатов диапазона с `DATETIME2(6)`.

### 2026-02-20 17:49:57
- Исправлена ошибка `Metadata mismatch found in from_delayed` в узле `SaveParquet` при `row_cap`: добавлено выравнивание dtype chunk-партиций к `ddf._meta` в `src/nodes/write/save_parquet.py` (включая кейс `str` vs `string` для `DWH_hash_PK`).
- Добавлен регрессионный unit-тест `test_apply_row_cap_aligns_chunk_dtypes_with_meta_string` в `tests/unit/src/nodes/write/test_save_parquet.py`, воспроизводящий mismatch `str/object` против ожидаемого `string` и проверяющий корректную работу после фикса.

### 2026-02-20 18:01:06
- Исправлена ошибка `Unknown dialect 'mssql'. Did you mean mysql?` в узле `WriteDataFrameToDB` при разборе `create_table_sql` через sqlglot.
- В `src/nodes/write/write_df_to_db.py` обновлен маппинг диалектов: `mssql`/`sqlserver` -> `tsql` для корректного `parse_one(..., read=...)`.
- Добавлены unit-тесты `tests/unit/src/nodes/write/test_write_df_to_db.py` (маппинг диалекта и разбор имени таблицы из MSSQL `CREATE TABLE`).

### 2026-02-20 19:04:25
- Исправлена валидация в `src/nodes/transform/df_add_time_delta.py` для ноды `AddTimeDeltaToDataFrame`.
- В `validation_column_type` добавлена проверка существования колонки перед проверкой типа, чтобы при отсутствии колонки выбрасывался `NodeValidationError`, а не `KeyError`.
- Проверено запуском `pytest tests/unit/src/nodes/transform/test_df_add_time_delta.py -q` — все тесты в модуле прошли.

### 2026-02-20 19:15:31
- Скорректировано предыдущее исправление ошибки валидации `AddTimeDeltaToDataFrame`.
- Первопричина была в параллельном запуске validation-хуков: в `src/node_dsl/base_node/mixins/validate_node.py` для стадии `ON_VALIDATION` установлен последовательный запуск (`concurrently=False`).
- Дублирующая проверка существования колонки удалена из `src/nodes/transform/df_add_time_delta.py:validation_column_type`.
- Проверено тестами: `pytest tests/unit/src/nodes/transform/test_df_add_time_delta.py tests/unit/src/nodes/transform/test_add_timedelta.py -q` — 5 passed.

### 2026-02-21 16:05:59
- Подготовлен итоговый отчёт по разработке фич `dvt_mcp` в формате Markdown: `tmp/dvt_mcp_features_report.md`.
- В отчёте описаны реализованные инструменты (`get_logs`, `get_projects`, `get_tasks`, `run_task`), покрытие тестами, обновления документации и архитектурные рекомендации по runtime/restart для script и docker режимов.

### 2026-02-21 16:08:09
- Подготовлен отдельный отчёт по новым фичам `dvt_mcp` для сервисов (информация о запущенных сервисах и перезапуск): `tmp/dvt_mcp_services_runtime_restart_report.md`.
- В отчёте описаны варианты архитектуры, оценка подходов (process scan/lock files/PyCharm API/supervisor), целевой дизайн для Windows-first окружения, протокол supervisor↔dvt_mcp через Valkey и поэтапный план внедрения.

### 2026-02-21 16:17:11
- Переписан отчёт `tmp/dvt_mcp_services_runtime_restart_report.md` под новый план: PyCharm plugin зафиксирован как единый источник правды для script-сервисов.
- В отчёте обновлены архитектура взаимодействия `dvt_mcp` ↔ plugin, контракт API (`health/services/restart`), требования к безопасности (loopback + token), модель ошибок (`plugin_unavailable`) и поэтапный план внедрения.

### 2026-02-21 16:21:46
- Обновлен отчёт `tmp/dvt_mcp_services_runtime_restart_report.md` с учетом важного дополнения: если плагин не подтверждает, что сервис запущен, `dvt_mcp` должен проверять этот сервис в Docker.
- В документ добавлены приоритет источников (`pycharm_plugin` -> `docker`), fallback-алгоритм для `get_runtime_info` и `restart_service`, а также соответствующие изменения в плане внедрения и тестировании.

### 2026-02-21 16:32:34
- Добавлен новый модуль `services/pycharm_plugin` (Этап 1): Gradle/Kotlin каркас, `plugin.xml`, локальный HTTP API (`/health`, `/v1/services`, `/v1/services/{service}/restart`), базовая token-авторизация и runtime/restart логика через run-конфигурации IDE.
- Зафиксирован mapping `service_name -> docker compose service` (`gateway`, `task_worker`, `task_scheduler`, `orchestrator`).
- Обновлен отчет `tmp/dvt_mcp_services_runtime_restart_report.md`: Этап 1 отмечен как завершенный.

### 2026-02-21 16:45:37
- Для `services/pycharm_plugin` добавлен Gradle Wrapper (`gradlew`, `gradlew.bat`, `gradle/wrapper/*`) для сборки без глобального `gradle`.
- Исправлена конфигурация сборки плагина: совместимый IntelliJ SDK (`2024.1`), Java target 17, корректный импорт `ProgramRunnerUtil`, фикс compile-ошибок и версия `kotlinx-serialization-json`.
- Проверена сборка `buildPlugin`: сформирован архив `services/pycharm_plugin/build/distributions/dvt-pycharm-plugin-0.1.0.zip`.
- README плагина обновлен командами запуска/сборки через wrapper.

### 2026-02-21 16:51:05
- Исправлена совместимость PyCharm-плагина с IDE ветки 253: в `services/pycharm_plugin/build.gradle.kts` для `patchPluginXml` установлен диапазон `since-build=241`, `until-build=253.*`.
- Повышена версия плагина до `0.1.1` для корректного обновления при установке.
- Пересобран архив: `services/pycharm_plugin/build/distributions/dvt-pycharm-plugin-0.1.1.zip`.

### 2026-02-21 17:00:29
- Завершен Этап 2 для runtime/restart в `dvt_mcp`.
- В `services/dvt_mcp/operations.py` добавлены: HTTP-клиент к локальному PyCharm plugin (`/health`, `/v1/services`, `/v1/services/{service}/restart`), Docker introspection через `docker compose ps --format json`, приоритет источников `pycharm_plugin -> docker` в `get_runtime_info`, и новая операция `restart_service` (plugin first, docker fallback).
- В `services/dvt_mcp/main.py` зарегистрирован новый tool `restart_service`.
- Добавлены unit-тесты сценариев runtime/restart fallback в `tests/unit/services/dvt_mcp/test_operations.py` и делегирование в `tests/unit/services/dvt_mcp/test_main.py`.
- Обновлены документы `services/dvt_mcp/README.md`, `AGENTS.md` и статус Этапа 2 в `tmp/dvt_mcp_services_runtime_restart_report.md`.

### 2026-02-21 17:12:26
- Обновлен runtime/restart контур в `dvt_mcp` по фидбеку удобства работы агента.
- В `services/dvt_mcp/operations.py` реализовано: компактный `get_runtime_info` (summary по умолчанию), `verbose` debug-режим, фильтр `services`, нормализованный `effective_status` (`running|stopped|restarting|unhealthy|unknown`), скрытие шумных Docker raw-полей в summary, и расширенная диагностика `attempts` в `restart_service`.
- В `services/dvt_mcp/main.py` обновлен tool `get_runtime_info` (новые параметры `services`, `verbose`).
- Добавлены/обновлены unit-тесты `tests/unit/services/dvt_mcp/test_operations.py` и `tests/unit/services/dvt_mcp/test_main.py`.
- Обновлена документация `services/dvt_mcp/README.md`, `AGENTS.md`, а также отчет `tmp/dvt_mcp_services_runtime_restart_report.md`.
- В плагине `services/pycharm_plugin` исправлен `/health`: `plugin_version` теперь берется из реального descriptor версии плагина через IntelliJ API; версия артефакта повышена до `0.1.2`.

### 2026-02-21 17:23:03
- Добавлена инфраструктура для автономной сборки и runtime-обновления PyCharm-плагина.
- В `services/pycharm_plugin/scripts/build_plugin.ps1` реализован авто-резолв JDK/JBR 17+ и сборка `gradlew.bat buildPlugin` (решает проблему запуска Gradle на Java 8).
- В плагин добавлен endpoint `POST /v1/update` для hot-update маппинга без пересборки; реализованы модели `UpdateRequest/UpdateResponse` и логика применения override-мэппингов в `DvtServiceRegistry`.
- В `services/pycharm_plugin/scripts/update_plugin_config.ps1` добавлен helper для отправки конфигурации в `/v1/update`.
- В `services/dvt_mcp` добавлены tool-ы `build_pycharm_plugin` и `update_pycharm_plugin_config` для автоматизации сборки и runtime-обновления плагина агентом.
- Обновлены `services/dvt_mcp/README.md`, `services/pycharm_plugin/README.md`, `AGENTS.md`, `tmp/dvt_mcp_services_runtime_restart_report.md` и unit-тесты `tests/unit/services/dvt_mcp/*`.

### 2026-02-21 17:25:19
- Исправлен `services/pycharm_plugin/scripts/build_plugin.ps1`: скрипт полностью переписан в ASCII без не-ASCII литералов/кавычек, чтобы исключить ошибки парсинга PowerShell из-за кодировки.
- Проверен запуск скрипта: синтаксические ошибки устранены, скрипт корректно доходит до шага Gradle build.

### 2026-02-24 13:57:52
- Добавлен скрипт `scripts/docker/unit_tests.py` для запуска unit-тестов в Docker через сервис `tester` из `docker/docker-compose.dev.yaml` с обязательным шагом сборки образа.
- Обновлен job `unit_tests` в `.gitlab-ci.yml`: прямые docker-команды заменены на запуск нового Python-скрипта.

### 2026-02-24 16:32:47
- Перенесен тестовый раннер из `docker/docker-compose.dev.yaml` в `docker/docker-compose.tests.yaml` и добавлены отдельные сервисы `tester_unit`, `tester_integration`, `tester_e2e` на одном образе `dvt/tester`.
- Обновлен скрипт `scripts/docker/unit_tests.py` под новый compose-override (`base + dev + tests`) и сервис `tester_unit`.
- Добавлены скрипты `scripts/docker/integration_tests.py` и `scripts/docker/e2e_tests.py` для запуска integration/e2e тестов через Docker.
- В `tests/e2e/fixtures/docker.py` исправлен путь к compose-файлам (`docker/docker-compose.base.yaml`, `docker/docker-compose.dev.yaml`) и добавлен флаг `E2E_SKIP_IMAGE_BUILD=1` для отключения повторной сборки внутри тестов.
- Актуализированы команды запуска тестов в Docker в `README.md` и `CLAUDE.md` на вызовы новых Python-скриптов.

### 2026-02-24 21:06:32
- Для запуска `scripts/docker/integration_tests.py` добавлены недостающие тестовые зависимости в `services/tester/requirements.txt` (`pymongo`, `minio`).
- В `docker/docker-compose.tests.yaml` для `tester_integration` и `tester_e2e` добавлены переменные `TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal`, `TESTCONTAINERS_RYUK_DISABLED=true` и `extra_hosts` с `host-gateway`, что устранило инфраструктурные ошибки старта testcontainers внутри Docker.
- Проверен запуск `scripts/docker/integration_tests.py`: сборка выполняется, тестовый набор стартует и доходит до прогона pytest; итог текущего состояния набора — `104 passed`, `15 failed` (функциональные падения тестов).

### 2026-02-24 21:17:05
- В `.gitlab-ci.yml` добавлена стадия `integration_tests` между `unit_tests` и `deploy_dev`, чтобы integration-прогоны выполнялись до этапа публикации образов.
- Добавлен job `integration_tests` с запуском `python3 scripts/docker/integration_tests.py` (аналогичные правила запуска и настройки, как у `unit_tests`, с зависимостью от `build`).

### 2026-02-24 21:37:01
- Добавлены unit-тесты для `core/db/read_v3` на валидацию лишних полей (`columns`), отсутствующих в источнике данных, в режимах `table` и `query`.
- Добавлен integration-набор `tests/integration/core/db/read_v3/test_read_v3_extra_fields_integration.py` с проверкой этих сценариев для всех поддерживаемых SQL-БД: Postgres, MySQL, MSSQL, Oracle и ClickHouse.
- В integration-тестах реализованы унифицированные helpers для создания/очистки таблиц и параметризация по engine fixtures, включая безопасный skip MSSQL при отсутствии `pyodbc`.

### 2026-02-24 22:03:12
- Дополнены тесты для `core/db/read_v3` на отсутствие технических/виртуальных колонок (`__dvt_*`) в итоговом `dask.dataframe.DataFrame` при разных параметрах чтения.
- В `tests/unit/core/db/read_v3/test_executor_sql.py` добавлены кейсы для `range`/`hash` сценариев с верхним регистром технических алиасов от драйвера.
- В `tests/integration/core/db/read_v3/test_read_v3_extra_fields_integration.py` добавлены параметризованные проверки по всем SQL-БД (Postgres, MySQL, MSSQL, Oracle, ClickHouse) для сценариев `table`/`query`, включая `partition_grouping`.
- Исправлен `SQLReadExecutor`: добавлено нормализованное (case-insensitive) сопоставление колонок для выбора индексной колонки и финальной проекции, чтобы технические поля не просачивались в результат.
- Исправлен `OracleDialect`: ужесточено правило простых идентификаторов (без начального `_`), чтобы технические алиасы в Oracle корректно квотировались и не вызывали `ORA-00911`.

### 2026-02-25 11:44:37
- Исправлено поведение `read_v3` при `partition_grouping` на пустом источнике: в `core/db/read_v3/partitioning/grouping.py` для случая `total_rows == 0` теперь формируется одна пустая партиция (`predicate_sql="1=0"`) вместо ошибки `partition_grouping ... produced no segments`.
- Добавлен unit-тест `test_table_mode_partition_grouping_prefix_for_empty_table_builds_single_empty_segment` в `tests/unit/core/db/read_v3/test_sqlite_e2e.py`.
- Добавлен integration-тест `test_read_v3_table_mode_partition_grouping_prefix_empty_table_integration` в `tests/integration/core/db/read_v3/test_read_v3_integration.py`.

### 2026-02-25 12:04:31
- Добавлен файл `core/db/read_v3/README.md` с документацией на русском языке по пакету `read_v3`.
- В README описаны: назначение пакета, high-level алгоритм (режимы table/query, выбор стратегий, поведение на пустых таблицах, ошибки), low-level устройство (планировщики, сегментация, executors, интеграция с Dask) и практические инструкции по расширению (новый диалект, режим grouping, стратегия/планировщик) с ссылками на исходный код и примерами использования.

### 2026-02-25 12:24:20
- Добавлен общий модуль `scripts/docker/test_runner.py` для запуска docker-тестов: парсинг аргументов, валидация целевого пути теста внутри `tests/<type>`, сборка команд `docker compose` и выполнение с окружением.
- Обновлены скрипты `scripts/docker/unit_tests.py`, `scripts/docker/integration_tests.py`, `scripts/docker/e2e_tests.py`: добавлен опциональный путь для точечного запуска тестов и поддержка дополнительных аргументов pytest; при отсутствии пути запускаются все тесты соответствующего типа.
- Изменен `services/dvt_mcp.run_pytest`: запуск переведен на `scripts/docker` с параметрами `test_type` (`unit|integration|e2e`) и `test_path`, сохранена поддержка дополнительных `arguments` и `timeout_sec`.
- Обновлены `services/dvt_mcp/main.py`, документация в `services/dvt_mcp/README.md` и блок `dvt_mcp` в `AGENTS.md`.
- Добавлены и обновлены unit-тесты для `services/dvt_mcp` и нового runner-модуля в `tests/unit/scripts/docker/test_test_runner.py`.

### 2026-02-25 14:28:50
- В `services/dvt_mcp/operations.py` расширен `get_tasks`: при запросе по точному `task_id` теперь добавляется поле `execution_insights` с извлеченными из логов данными (start nodes, execution order, обработанные ноды, `read_total_rows`, `inserted_rows`, оценка дельты строк и признаки запуска через `__service_output__`/`WriteDataFrameToDB`).
- Добавлен unit-тест `test_get_tasks_task_id_includes_execution_insights` в `tests/unit/services/dvt_mcp/test_operations.py`.
- Обновлен блок `dvt_mcp` в `AGENTS.md` с описанием нового обогащения ответа `get_tasks`.

### 2026-02-25 14:42:27
- В `src/nodes/transform/df_group_by_agg.py` исправлена агрегация группировки: добавлен `dropna=False` в `groupby`, чтобы строки с `NULL` в ключах группировки не отбрасывались.
- Добавлен регрессионный unit-тест `tests/unit/src/nodes/transform/test_df_group_by_agg.py`, который проверяет сохранение группы с `NULL` ключом и корректный `count`.

### 2026-02-25 15:24:01
- Добавлен файл `tests/unit/services/dvt_mcp/conftest.py`.
- Реализован автоскип для тестов каталога `tests/unit/services/dvt_mcp` при запуске внутри Docker (детекция через `/.dockerenv` и `/proc/1/cgroup`).
- Проверен локальный прогон `tests/unit/services/dvt_mcp`: все тесты проходят вне Docker.

### 2026-02-25 15:36:17
- Оптимизирована сборка `services/tester/docker/dev.Dockerfile`:
- - удалено `COPY services/ /services` из dependency-слоя;
- - добавлено копирование только `requirements.txt` (проектного и сервисных);
- - формирование списка зависимостей переведено на фиксированный список `-r` файлов.
- Это позволяет сохранять кэш установки зависимостей при изменениях исходного кода сервисов.
- Добавлен корневой `.dockerignore` для уменьшения build context (`.git`, виртуальные окружения, кэши, `tmp`, `trash`, `services/ui/node_modules` и др.), что ускоряет `docker compose build` для `tester_*` и других сервисов с контекстом `.`.

### 2026-02-25 15:51:49
- Дополнительно расширен `.dockerignore` для ускорения передачи контекста сборки:
- - добавлены исключения `data/`, `services/pycharm_plugin/build/`, `services/pycharm_plugin/.gradle*`, `services/ui/.tmp/`, `services/ui/.codex/`, `services/ui/.idea/`.
- Проверена сборка `tester_unit` через compose после изменений: сборка успешна, размер передаваемого контекста для шага `tester_unit` снижен с ~1.27GB до ~245KB.

### 2026-02-25 16:34:45
- Исправлена сборка S3-путей в узлах `LoadExcel`, `SaveCSV` и `SaveParquet`: убрано некорректное `.replace("//", "/")`, из-за которого схема `s3://` превращалась в `s3:/`.
- Добавлена безопасная сборка object key через склейку сегментов пути без порчи протокола.
- Перезапущены интеграционные тесты: все проходят (`150 passed`).

### 2026-02-25 18:04:10
- В `docker/docker-compose.tests.yaml` для сервисов `tester_integration` и `tester_e2e` добавлена переменная окружения `TC_MAX_TRIES="600"`.
- Это увеличивает таймаут ожидания готовности testcontainers (включая Oracle) в CI и снижает количество ложных падений по таймауту старта контейнеров.

### 2026-02-26 11:29:37
- Добавлена поддержка управляющих сигналов выполнения нод через новый тип `IO.SIGNAL`.
- В `BaseNode` добавлены глобальные порты `signal_in` (множественные подключения) и `signal_out` для задания строгого порядка выполнения без передачи данных.
- Обновлена сборка графа и kwargs пайплайна: множественные link-подключения теперь поддерживаются по `allow_multiple_connections`, а для `signal_in` несколько входящих связей используются как зависимости выполнения.
- Синхронизированы фронтовые типы и схемы (`Io`/`zIo`) с новым значением `SIGNAL`, добавлен цвет для signal-порта и включен `SIGNAL` в connection-required типы (включая subgraph).
- Добавлены и обновлены unit-тесты для `signal`-связей и наследуемых глобальных полей BaseNode.

### 2026-02-26 11:44:26
- Обновлен `AGENTS.md`: добавлен раздел `Gateway/OpenAPI & UI Rules`.
- Зафиксировано правило обязательного перезапуска сервиса `Gateway` при изменении сущностей (моделей/схем данных), влияющих на Gateway API, так как `services/ui/src/shared/gatewayClient` генерируется по OpenAPI от Gateway.
- Добавлен запрет на внесение правок в `services/ui`, поскольку локальная разработка UI ведется в другой директории.

### 2026-02-26 11:51:28
- Добавлено поле `show_signal_io` в модель `GraphNode` и протянуто через HTTP-схемы/DTO (`showSignalIo`) для чтения и сохранения флага отображения сигналов в UI.
- Обновлен batch update граф-нод: добавлен `show_signal_io` с безопасным boolean-cast в SQL `COALESCE`.
- Обновлено копирование проекта в Gateway: поле `show_signal_io` теперь переносится при копировании `graph_nodes`.
- Добавлена миграция `0030_add_show_signal_io_to_graph_nodes.py` (новый столбец `graph_nodes.show_signal_io`, default `false`).
- Обновлены unit-тесты DTO и SQL-генерации для нового поля.

### 2026-02-26 12:33:53
- Добавлены новые tool-ноды `ExecuteSQL` и `ExecutePython` в `src/nodes/tool`.
- `ExecuteSQL` выполняет SQL-код через переданный `Engine` и выставляет сигнал выполнения.
- `ExecutePython` выполняет переданный Python-код в локальном контексте ноды (с доступом к `node`, `logger`, `variables`, `project_variables`) и выставляет сигнал выполнения.
- Для совместимости с сервисным output-добавлением в графе обе ноды получили выход `output` типа `IO.SIGNAL` (в дополнение к базовому `signal_out`).
- Обновлен экспорт `src/nodes/tool/__init__.py`.
- Добавлены unit-тесты `tests/unit/src/nodes/tool/test_execute_sql.py` и `tests/unit/src/nodes/tool/test_execute_python.py`.

### 2026-02-26 13:06:57
- Рефакторинг `NodeDefinition`: поля `input_definitions` и `output_definitions` переведены со списков на mapping по `attr_name` в `src/schemas/node_definition.py`.
- Обновлены backend-потребители нового формата в `src/node_dsl/registry/definitions.py`, `src/pipeline/graph_utils.py`, `src/utils/graph.py`, `src/pipeline/validation.py`, `src/pipeline/processor.py`.
- Добавлена нормализация legacy-списков в `NodeDefinition` (pre-validation) для обратной совместимости при создании модели.
- Адаптирован `scripts/misc/update_locales.py` для извлечения i18n из mapping-формата.
- Обновлены unit-тесты `tests/unit/src/pipeline/test_graph_utils.py` под словарный контракт; прогон `tests/unit/src/pipeline` успешен (17 passed).

### 2026-02-27 11:24:50
- Добавлены верхние лимиты в `config.py` и `config_prod.py` (класс `OTHER`) для SQL-параллелизма и пула SQLAlchemy Engine: `SQL_BULK_INSERT_MAX_WORKERS`, `SQL_ENGINE_MAX_CONNECTIONS`, `SQL_ENGINE_POOL_TIMEOUT_SEC`.
- В `src/nodes/write/write_df_to_db.py` ограничено фактическое значение `bulk_insert_num_workers` по новому верхнему лимиту.
- В `core/db/insert.py` добавлено создание Engine с ограничениями пула для SQL-бэкендов (кроме SQLite), чтобы снизить риск исчерпания файловых дескрипторов.
- Оптимизированы `RedisCacheManager` и `RedisIndexManager`: добавлена периодическая очистка и закрытие idle/устаревших Redis-соединений (в том числе для закрытых event loop), а также явный метод `close()` для принудительного освобождения клиентов.

### 2026-02-27 11:31:53
- Добавлены интеграционные тесты на сценарий `Too many open files`.
- Добавлен кроссплатформенный fault-injection тест `tests/integration/src/managers/test_too_many_open_files.py` для `RedisCacheManager` и `RedisIndexManager`, проверяющий корректную обработку `redis.exceptions.ConnectionError` с `Error 24`.
- Добавлен linux-only docker-тест `tests/integration/services/task_worker/test_too_many_open_files_docker.py`, который запускает контейнер с низким `nofile` и проверяет реальное достижение `EMFILE` внутри контейнера.

### 2026-02-27 14:04:14
- Исправлены пункты 1 и 2 backend-аудита от 2026-02-27.
- В metadata-путях (`read_query_from_db.py`, `read_query_from_db_v2.py`, `read_query_from_db_v3.py`, `sql_query_to_metadata.py`) добавлено гарантированное закрытие `raw_connection/cursor` через `contextlib.closing`.
- В gateway-утилите `services/gateway/routes/utils/sql_query_to_metadata.py` для ClickHouse исправлено построение `DESCRIBE TABLE` на использование нормализованного `raw_query` вместо исходного `query`.

### 2026-02-27 14:51:42
- Переведен `task_worker` на выполнение задач напрямую в Celery worker child-процессе без `SubprocessRunner`.
- Обновлена конфигурация Celery: по умолчанию `prefork`, добавлены `CELERY_WORKER_MAX_TASKS_PER_CHILD` и опциональный `CELERY_WORKER_MAX_MEMORY_PER_CHILD`.
- Реализована отмена через `celery_app.control.revoke(..., terminate=True)` и привязка `celery task_id` к `task.task_id` в оркестраторе.
- Обновлены heartbeat и unit-тесты `task_worker` под новую модель выполнения.
- Актуализирован `services/task_worker/README.md` под процессный рецикл после каждой задачи.

### 2026-02-27 15:05:53
- Удален мертвый код `SubprocessRunner`: удалены `services/task_worker/subprocess_runner/*` и `services/task_worker/deps/subprocess_runner.py`.
- Проведен рефактор heartbeat/registry: поле `is_busy` удалено из моделей и обработки heartbeat (`src/schemas/internal/worker_hearbeat.py`, `services/task_worker/schemas/heartbeat.py`, `src/schemas/internal/worker_state.py`, `services/orchestrator/listeners/heartbeat.py`, `services/orchestrator/worker_registry.py`).
- Из `services/orchestrator/deps/worker_event_callbacks.py` удалены неиспользуемые переключения занятости воркера.
- Добавлены unit-тесты `tests/unit/services/orchestrator/test_scheduler.py` для проверки:
- - передачи `task_id` в `celery_app.send_task`;
- - отмены через `celery_app.control.revoke(..., terminate=True)`;
- - отсутствия простаивания задач в очереди при наличии живого воркера.
- Проверка: `pytest` для `task_worker` и `orchestrator/scheduler` — 8 passed.

### 2026-02-27 15:11:49
- Исправлен запуск `task_worker` в Celery `prefork/spawn` режиме: в `services/task_worker/main.py` добавлен bootstrap, который гарантирует добавление корня проекта в `sys.path` и `PYTHONPATH` перед запуском `worker_main`.
- Это устраняет падение дочерних процессов с `ModuleNotFoundError: No module named 'services.task_worker'` при импорте task-модулей в `SpawnPoolWorker`.

### 2026-02-27 15:16:14
- Добавлен bootstrap импорта для запуска `task_worker` через `scripts/services/run_task_worker.py`: теперь перед стартом воркера принудительно выставляются корень проекта в `sys.path`/`PYTHONPATH` и `cwd` на корень репозитория.
- Это устраняет `ModuleNotFoundError: No module named 'services.task_worker'` в `SpawnPoolWorker` при запуске через конфигурацию PyCharm.

### 2026-02-27 15:23:16
- Исправлено падение `task_worker` в `SpawnPoolWorker` с `ValueError: not enough values to unpack (expected 3, got 0)` в `celery.app.trace.fast_trace_task`.
- В `services/task_worker/celery_app.py` добавлен обработчик `worker_process_init`, который в дочернем процессе проверяет `celery.app.trace._localized` и при необходимости вызывает `setup_worker_optimizations(celery_app)`.
- Это гарантирует корректную инициализацию fast-trace локалов Celery в child-процессах при spawn/prefork запуске.

### 2026-02-27 17:15:36
- Исправлен `services/task_worker/tasks/worker_tasks.py`: обработка финальных статусов задачи сделана идемпотентной при конфликте переходов (например, `ERROR -> ERROR`), чтобы воркер не падал в `Task crashed in celery worker` при повторной установке ошибки.
- Добавлен unit-тест `test_handle_task_does_not_crash_on_redundant_error_transition` в `tests/unit/services/task_worker/tasks/test_worker_tasks.py`.
- Проверены тесты: `tests/unit/services/task_worker/tasks/test_worker_tasks.py` и `tests/unit/services/task_worker/test_celery_app.py` проходят.

### 2026-02-27 17:46:08
- Исправлены проблемы логирования в `task_worker`:
- - В `scripts/services/run_task_worker.py` переменная окружения `SERVICE_NAME=task-worker` теперь задается до `import config`, чтобы логи писались с корректным `service_name`, а не `no-service-name`.
- - В `services/task_worker/celery_app.py` вынесена инициализация sink-логгеров в отдельный блок и добавлена инициализация DB/WS sink в `worker_process_init`, чтобы логи из Celery child-процессов (где выполняются задачи) попадали в БД и WebSocket.
- - Добавлен `worker_process_shutdown` для корректного закрытия ресурсов логирования в child-процессе.
- - В `services/task_worker/tasks/worker_tasks.py` добавлен `logger.contextualize(...)` на время выполнения задачи, чтобы все вложенные логи пайплайна получали `user_id/task_id/project_id/send_ws_messages` и проходили фильтр отправки в WS.
- - Обновлены unit-тесты `tests/unit/services/task_worker/tasks/test_worker_tasks.py`.
- Проверка: `tests/unit/services/task_worker/tasks/test_worker_tasks.py` и `tests/unit/services/task_worker/test_celery_app.py` проходят (6 passed).

### 2026-02-27 17:47:05
- Уточнен контекст логирования в `services/task_worker/tasks/worker_tasks.py`: `logger.contextualize(...)` применен внутри async-корутины исполнения и обновления статусов, чтобы контекст (`user_id/task_id/project_id`) гарантированно попадал в логи из loop-thread `AsyncRunner`.
- Повторно проверены unit-тесты `tests/unit/services/task_worker/tasks/test_worker_tasks.py` и `tests/unit/services/task_worker/test_celery_app.py` — проходят (6 passed).

### 2026-02-27 18:04:29
- Исправлена деградация Celery prefork на dev-стенде (`Timed out waiting for UP message` / `fork_posix ... gRPC ... skipping fork handlers`).
- Изменения в `services/task_worker/celery_app.py`:
- - Для `prefork` инициализация DB/WS sink в `MainProcess` отключена; sink теперь инициализируются только в `worker_process_init` (child), чтобы не форкаться при активных gRPC-потоках в родителе.
- - Добавлен отдельный `shutdown` для лог-sink (`_shutdown_log_sinks`) и применен в `worker_process_shutdown` вместо полного `_shutdown`, чтобы child не трогал heartbeat/gateway-состояние родительского процесса.
- - Основной `_shutdown` теперь переиспользует `_shutdown_log_sinks`.
- Проверка: unit-тесты `tests/unit/services/task_worker/test_celery_app.py` и `tests/unit/services/task_worker/tasks/test_worker_tasks.py` проходят.

### 2026-02-27 18:18:04
- Устранена вероятная причина `Timed out waiting for UP message` после успешной задачи в prefork-воркере.
- Изменения:
- - В `services/task_worker/celery_app.py` удалена блокирующая инициализация лог-sink из `worker_process_init` (child startup path).
- - Добавлена ленивая инициализация sink для процесса выполнения задачи: `ensure_log_sinks_for_task_process()` с таймаутом и безопасным деградированием.
- - В `services/task_worker/tasks/worker_tasks.py` вызов `ensure_log_sinks_for_task_process()` добавлен в `handle_task` и `handle_task_control`.
- - В `shutdown` лог-sink флаг инициализации child-process сбрасывается.
- Проверка: unit-тесты `tests/unit/services/task_worker/tasks/test_worker_tasks.py` и `tests/unit/services/task_worker/test_celery_app.py` проходят.

### 2026-02-27 18:19:21
- Дополнительный фикс startup child-процессов Celery на Linux:
- - В `services/task_worker/celery_app.py` workaround с `celery.app.trace` и `WindowsSelectorEventLoopPolicy` ограничен только платформой Windows.
- - На Linux `worker_process_init` теперь не выполняет лишнюю инициализацию, чтобы ускорить старт child и снизить риск `Timed out waiting for UP message`.
- Проверка: `tests/unit/services/task_worker/test_celery_app.py` и `tests/unit/services/task_worker/tasks/test_worker_tasks.py` проходят.

### 2026-02-27 18:41:42
- Исправлен запуск dockerized unit-тестов на Windows-профиле пользователя с ограниченными правами к `%USERPROFILE%/.docker`:
- - В `scripts/docker/unit_tests.py` добавлен локальный `DOCKER_CONFIG` в каталоге проекта (`tmp/docker-config`) и его автоматическое создание, чтобы избежать ошибки `buildx/.lock: Access is denied`.
- Исправлен флейк в `tests/unit/services/task_worker/test_celery_app.py`:
- - Проверки результата `_shutdown()` перенесены до восстановления глобального состояния `logger_db_sink`, чтобы тест корректно работал в полном прогоне и не зависел от предыдущих тестов.
- Проверка:
- - Локально `tests/unit/services/task_worker/test_celery_app.py` проходит.
- - Полный запуск `scripts/docker/unit_tests.py` прошел успешно: `593 passed`.

### 2026-02-27 18:57:44
- Исправлен сценарий, когда `task_worker` обрабатывал только одну задачу и переставал брать новые.
- В `services/task_worker/celery_app.py` изменен `worker_process_shutdown`: убран вызов тяжелого async-shutdown sink-логирования (`_shutdown_log_sinks`) в child-процессе перед его завершением.
- Причина: при `worker_max_tasks_per_child=1` блокирующий shutdown в child мог задерживать/ломать его завершение и мешать `MainProcess` поднять следующий `ForkPoolWorker`.
- Теперь в child shutdown выполняется только остановка loop-thread (`runner.stop()`), а полный shutdown sink остается в основном shutdown-пути процесса.
- Проверка: `tests/unit/services/task_worker/test_celery_app.py` и `tests/unit/services/task_worker/tasks/test_worker_tasks.py` проходят (6 passed).

### 2026-02-27 19:12:35
- Исправлен вероятный корень зависания `task_worker` после первой задачи в Docker/Linux: `AsyncRunner` сделан fork-safe.
- Изменения в `services/task_worker/helpers/async_runner.py`:
- - Добавлена привязка раннера к PID процесса (`_runner_pid`) и проверка смены PID в `get_async_runner()`.
- - При смене PID или невалидном состоянии раннера создается новый экземпляр `AsyncRunner`.
- - Добавлена проверка здоровья раннера (`is_healthy`) и защита в `run()` от использования неработающего loop-thread.
- - Улучшен `stop()` (безопасная остановка и закрытие loop).
- Добавлены unit-тесты `tests/unit/services/task_worker/helpers/test_async_runner.py`:
- - переиспользование healthy раннера в одном PID,
- - пересоздание раннера после смены PID (fork),
- - пересоздание unhealthy раннера в том же PID.
- Проверка:
- - Локально: `tests/unit/services/task_worker/helpers/test_async_runner.py`, `tests/unit/services/task_worker/test_celery_app.py`, `tests/unit/services/task_worker/tasks/test_worker_tasks.py` — 9 passed.
- - Dockerized: `scripts/docker/unit_tests.py` — 596 passed.

### 2026-03-02 17:42:46
- В `services/gateway/routes/utils/create_table.py` добавлены новые роуты:
- - `POST /utils/create-table-sql` для генерации SQL `CREATE TABLE` по `DataFrameMetadata` и `DBMetadata` входного подключения.
- - `POST /utils/create-table-from-sql` для создания/пересоздания таблицы из SQL с режимами `on_exists`.
- Добавлены общие хелперы для построения SQLAlchemy Engine из метаданных подключения с расшифровкой пароля (если он зашифрован), выбора SQLGlot-диалекта и извлечения имени таблицы из DDL.
- Исправлен сценарий `on_exists="error"` в существующем роуте `/utils/create-table` (корректный HTTP 400 вместо некорректного вызова исключения).
- Добавлены unit-тесты `tests/unit/services/gateway/routes/utils/test_create_table_sql.py` на генерацию DDL и создание таблицы из SQL (включая `on_exists="ignore"`).

### 2026-03-03 17:46:07
- В `POST /utils/create-table-from-sql` добавлена логика создания схемы по аналогии с нодой `WriteDataFrameToDB`: перед выполнением DDL теперь проверяется наличие схемы и при необходимости она создается.
- Реализована отдельная ветка для Oracle (`CREATE SCHEMA AUTHORIZATION <schema>`), для остальных поддерживаемых SQL-диалектов используется `CreateSchema`, а для диалектов без поддержки схем (`sqlite/mysql/mariadb/clickhouse`) создание схемы пропускается с логированием.

### 2026-03-04 16:15:09
- Заполнен новый модуль `core/db/ddl_utils.py` и перенесены общие DDL-утилиты из слоя ноды/роута без изменения их текущего использования: маппинг диалектов SQLAlchemy→SQLGlot, парсинг `CREATE TABLE` (таблица/схема/колонки), нормализация PK-колонок, преобразование `DataFrameMetadata` в `DBColumn`, сборка `Engine` из строки/метаданных подключения и создание схемы с Oracle-веткой.

### 2026-03-04 16:18:47
- В `services/gateway/routes/utils/create_table.py` интегрированы функции из `core/db/ddl_utils.py`: сборка Engine (`build_engine`, `build_engine_from_metadata`), парсинг DDL (`extract_create_table_table_and_schema`), подготовка PK (`get_primary_key_cols`), конвертация метаданных DataFrame в DB-колонки (`build_db_columns_from_df_metadata`) и создание схемы (`ensure_schema_exists`).
- Удалены локальные дублирующие утилиты роута (`_build_engine`, `_build_engine_from_metadata`, `_get_sqlglot_dialect`, `_extract_table_name_and_schema`, `_get_primary_key_cols`, `_build_db_columns_from_df_metadata`).

### 2026-03-04 16:21:12
- В `src/nodes/write/write_df_to_db.py` интегрированы утилиты из `core/db/ddl_utils.py`:
- - парсинг имени таблицы из DDL переведен на `extract_create_table_table_name`;
- - извлечение списка колонок из DDL переведено на `extract_create_table_column_names`;
- - маппинг диалекта SQLAlchemy→SQLGlot переведен на `get_sqlglot_dialect_from_engine`.
- Локальный словарь `DIALECT_SA_TO_SG` и прямое использование `sqlglot.parse_one/exp` удалены из ноды. Для обратной совместимости сохранен метод `_get_sg_dialect` как тонкая обертка над общей утилитой.

### 2026-03-04 16:27:47
- В `src/nodes/write/write_df_to_db.py` удалены вспомогательные методы-обертки для SQLGlot (`_get_sg_dialect` и `_extract_create_table_sql_table_name`), нода переведена на прямое использование утилит из `core/db/ddl_utils.py` (`extract_create_table_table_name`, `extract_create_table_column_names`).
- Покрытие соответствующей логики перенесено из ноды в `tests/unit/core/db/test_ddl_utils.py`: добавлены тесты маппинга диалектов, парсинга `CREATE TABLE` (таблица/схема/колонки), нормализации PK, конвертации `DataFrameMetadata -> DBColumn`, сборки Engine и безопасного no-op создания схемы для SQLite.

### 2026-03-04 16:39:38
- В `src/nodes/write/write_df_to_db.py` добавлены докстринги ко всем методам класса `WriteDataFrameToDB` (включая приватные методы). Изменения носят только документирующий характер и не меняют бизнес-логику узла.

### 2026-03-04 16:41:28
- В `src/nodes/write/write_df_to_db.py` все докстринги методов класса `WriteDataFrameToDB` переписаны на русский язык и расширены: добавлено краткое описание назначения и ключевых шагов логики для каждого метода без изменения поведения кода.

### 2026-03-04 17:04:17
- Реализована новая нода `src/nodes/write/write_df_to_db_v2.py` по явному флоу `prepare -> plan -> execute` без изменения бизнес-логики режимов `append/truncate/recreate`.
- Вынесена явная подготовка контекста записи (`WriteContext`) и плана выполнения (`ExecutionPlan`), сохранены ветки `create_table_sql`, temp-replace для truncate и bulk insert стратегии (SQLAlchemy/ClickHouse).
- Исправлена совместимость с Node DSL: удален `from __future__ import annotations`, который ломал резолв аннотаций при регистрации ноды.

### 2026-03-04 17:31:26
- Обновлена логика `WriteDataFrameToDBV2` в `src/nodes/write/write_df_to_db_v2.py` по новому требованию lifecycle.
- Для режимов `append` и `truncate` отключено авто-создание таблицы: при отсутствии таблицы теперь прокидывается ошибка отражения (`autoload`) без скрытого `CREATE`.
- Для режима `recreate` создание таблицы выполняется только после `DROP` существующей таблицы; если таблица отсутствует до запуска ноды, также прокидывается ошибка.

### 2026-03-04 17:36:45
- В `src/nodes/write/write_df_to_db_v2.py` изменена проверка отсутствующей таблицы на явный `ValueError` с понятным текстом, вместо неявного падения через `autoload_with`.
- Сообщение ошибки теперь включает полное имя таблицы (`schema.table`) и текущий режим записи, чтобы поведение было однозначным для `append/truncate/recreate`.

### 2026-02-26 14:16:02
- Исправлена сборка сервисной выходной ноды в `src/utils/graph.py`: вместо жесткого `output` теперь выбирается корректный выход узла (`output` -> первый несигнальный -> `signal_out`).
- Добавлены unit-тесты в `tests/unit/src/utils/test_graph.py` для проверки линковки `__service_output__` к `variable` (CreateVariable) и к `signal_out` (ExecuteSQL).
- Это устраняет падение пайплайна с ошибкой `Missing output 'output'` для узлов без порта `output`.

### 2026-02-26 14:48:37
- Исправлена обработка несовместимого metadata-cache в `src/pipeline/processor.py`.
- В `_try_restore_node_meta_cache_and_skip` вместо `ValueError` при несовпадении ключей кэша и определения ноды теперь выполняется мягкий fallback (cache miss) с предупреждением в логах.
- Добавлена нормализация legacy-метаданных: если в кэше отсутствуют некоторые выходы (например, `signal_out`), недостающие ключи дополняются значением `None`.
- Добавлен unit-тест `test_restore_meta_cache_accepts_legacy_metadata_without_signal_out` в `tests/unit/src/pipeline/test_processor.py`.
- Проверено запуском `pytest tests/unit/src/pipeline/test_processor.py` — все тесты прошли.

### 2026-02-26 18:04:56
- Исправлена генерация метаданных DataFrame: в `core/metadata/df_metadata.py` добавлена фильтрация служебных индексных имен с префиксом `__dvt_`, чтобы внутренний индекс `__dvt_partition_bucket` из `read_v3` не попадал в `columns` выходной меты.
- Добавлен unit-тест `test_get_df_metadata_skips_internal_dvt_index` в `tests/unit/core/metadata/test_df_metadata.py`, проверяющий, что служебный индекс не публикуется в метаданных.
- Проверка: `tests/unit/core/metadata/test_df_metadata.py` — 6 passed.

### 2026-02-28 14:43:38
- Подготовлен подробный аудит клиентских подключений и рисков `Too many open files`.
- Добавлен отчет `tmp/fd_connection_audit_2026-02-28.md` с инвентаризацией используемых клиентских библиотек, анализом lifecycle соединений, рисков утечек FD и разбором docker-compose конфигураций.

### 2026-02-28 15:13:05
- Добавлены новые скрипты `scripts/docker/build_prod.py` и `scripts/docker/deploy_prod.py`.
- `build_prod.py` выполняет локальную prod-сборку Docker-образов через `docker compose` с файлами `docker/docker-compose.base.yaml`, `docker/docker-compose.dev.yaml` и `docker/docker-compose.prod.override.yaml` без публикации в удаленный registry.
- `deploy_prod.py` запускает локальное prod-окружение через ту же связку compose-файлов, предварительно проверяя/создавая сеть `dvt-net` и применяя масштабирование `task-worker` через переменную `DVT_TASK_WORKERS_COUNT`.

### 2026-03-02 13:57:22
- Исправлена фильтрация метаданных в `src/node_dsl/base_node/mixins/metadata_node.py`: исключение `SIGNAL` теперь сравнивается по строковому значению типа, чтобы перегруженный `IO.__eq__` не отбрасывал все выходы ноды.
- Сохранена фильтрация только валидных output-полей для ветки `infer_metadata`.
- Добавлен регрессионный unit-тест `tests/unit/src/node_dsl/test_metadata_node.py`, проверяющий, что для не-signal output метаданные не пустые, а `signal_out` исключается.

### 2026-03-02 16:11:37
- Ужесточено поведение `read_v3`:
- - В `core/db/read_v3/dask.py` включена строгая проверка метаданных (`verify_meta=True`) в `dd.from_delayed`.
- - В `core/db/read_v3/executors/sql.py` удалено «мягкое» приведение типов: ошибки `astype`/datetime-преобразований больше не игнорируются и теперь выбрасываются как `ReadV3ExecutionError` с контекстом (stage/segment, dtype, sample values).
- - Для datetime-приведения заменен `errors="coerce"` на `errors="raise"`.
- Добавлены интеграционные тесты в `tests/integration/core/db/read_v3/test_read_v3_integration.py`:
- - Проверка явного падения на невалидном bool-касте (`'false'/'true'` в boolean-колонке) для table mode.
- - Проверка падения по `verify_meta`-рассинхрону для query mode.

### 2026-03-02 16:32:18
- Доработан строгий bool-cast в `read_v3`, чтобы не ломать чтение boolean-полей со строковыми значениями из БД:
- - В `core/db/read_v3/executors/sql.py` добавлена строгая нормализация bool (`_normalize_boolean_series`) с поддержкой только допустимых значений (`true/false`, `1/0`, `yes/no`, `y/n`, `t/f`, `bool`, `NULL`).
- - При любом недопустимом значении теперь выбрасывается явная ошибка `ReadV3ExecutionError` с контекстом (колонка, stage/segment, sample values), без fallback и без проглатывания.
- Обновлены интеграционные тесты `tests/integration/core/db/read_v3/test_read_v3_integration.py`:
- - Добавлен кейс успешного чтения bool-like строк (`false/true/1/0/NULL`) в table mode.
- - Добавлен кейс явного падения на невалидном bool-литерале (`not_bool`) в table mode.
- - Сохранен кейс строгого падения по `verify_meta` для query mode.
- Проверка: `8 passed` для `tests/integration/core/db/read_v3/test_read_v3_integration.py`.

### 2026-03-02 18:21:56
- В `core/db/read_v3/executors/sql.py` изменена типизация `read_v3`: для `ValueKind.STRING` установлен единый pandas dtype `string` вместо fallback в `object`.
- В `_apply_output_type_hints` добавлен явный жесткий каст строковых колонок (`astype("string")`) в партициях, чтобы метаданные и фактические партиции были согласованы.
- Добавлены тесты:
- - unit: `tests/unit/core/db/read_v3/test_executor_sql.py` (`test_dtype_for_kind_maps_string_to_string_dtype`, `test_load_partition_casts_string_columns_to_string_dtype`);
- - integration: `tests/integration/core/db/read_v3/test_read_v3_integration.py` (`test_read_v3_table_mode_uses_string_dtype_for_string_columns_integration`).
- Прогон целевых тестов: unit `tests/unit/core/db/read_v3/test_executor_sql.py` (12 passed), integration `tests/integration/core/db/read_v3/test_read_v3_integration.py` (9 passed).

### 2026-03-02 18:45:24
- Обновлены `scripts/docker/deploy_dev.py` и `scripts/docker/deploy_prod.py`: аргумент `--remove-orphans` убран из поведения по умолчанию и добавлен как опциональный CLI-флаг.
- В `.gitlab-ci.yml` обновлен вызов `scripts/docker/deploy_dev.py` — теперь он запускается с `--remove-orphans`.

### 2026-03-02 20:37:20
- Ужесточен `read_v3` без fallback по типам: в `planner/query.py` добавлена строгая валидация `UNKNOWN` для выходных колонок и ключа партиционирования с выборкой non-null sample; в `planner/table.py` добавлен запрет `UNKNOWN` для выходных колонок и partition key.
- В `executors/sql.py` удален путь к `object`-fallback: `ValueKind.UNKNOWN` теперь вызывает `ReadV3ExecutionError`.
- Расширена нормализация типов в `dialects/base.py` (unwrap `Nullable(...)` и `LowCardinality(...)`).
- Обновлены и добавлены тесты под новый контракт: unit (`test_sqlite_e2e.py`, `test_executor_sql.py`, новый `test_dialect_base.py`), integration (`test_read_v3_integration.py`, матрица `read_query_from_db_v3`), и скорректированы ожидания ClickHouse для `date_col`.
- Финальный прогон: `pytest tests/unit -q` -> 616 passed; `pytest tests/integration -q` -> 158 passed, 1 skipped.

### 2026-03-03 14:11:40
- Исправлена корневая причина гонки инициализации `AsyncLoopWorker` в `src/runtime/async_loop_worker.py`:
- - добавлена потокобезопасность через `RLock` для жизненного цикла loop/thread (`bind_loop`, `ensure_own_loop`, `start`, `submit`, `stop`);
- - предотвращен конкурентный мульти-старт нескольких `AsyncLoopWorker`-потоков;
- - улучшена безопасная остановка loop и очистка ссылок на thread/loop.
- Добавлен быстрый hotfix в `src/node_dsl/base_node/df_output.py`:
- - в `DFOutputBaseNode.execute` (FULL-режим) добавлен ранний prewarm `async_worker.ensure_own_loop()` перед `map_partitions`.
- Добавлены регрессионные unit-тесты:
- - `tests/unit/src/runtime/test_async_loop_worker.py` — проверка одиночного запуска loop при конкурентной нагрузке;
- - `tests/unit/src/node_dsl/test_df_output_prewarm.py` — проверка prewarm в FULL и отсутствия prewarm в `METADATA_ONLY`.
- Проверка:
- - `pytest tests/unit/src/runtime/test_async_loop_worker.py tests/unit/src/node_dsl/test_df_output_prewarm.py -q` -> `3 passed`.
- - Дополнительно подтверждено поведение stress-сценарием: `async_loop_worker_threads 1` при `map_partitions(...).compute(num_workers=128)`.

### 2026-03-03 16:08:02
- Исправлена утечка технических колонок `__dvt_*` в пайплайне DataFrame.
- В `core/utils/_pandas.py` добавлен единый helper `is_internal_dvt_name`, обновлен `get_useful_indexes` для исключения технических индексных имен.
- В `core/metadata/df_metadata.py` применен единый фильтр технических имен как для индексов, так и для обычных колонок метаданных.
- В `src/nodes/transform/df_join.py` добавлена пост-очистка результата join от колонок `__dvt_*` (включая варианты с суффиксами merge), удален временный отладочный вывод колонок.
- Добавлены/обновлены unit-тесты: `tests/unit/core/utils/test_pandas_utils.py`, `tests/unit/core/metadata/test_df_metadata.py`, `tests/unit/src/nodes/transform/test_df_join.py`.
- Проверка: целевые unit-тесты проходят.

### 2026-03-03 17:52:01
- Добавлена миграция `migrations/versions/0032_migrate_read_from_db_nodes_v2_to_v3.py` для перевода нод `ReadTableFromDBV2` и `ReadQueryFromDBV2` в `ReadTableFromDBV3` и `ReadQueryFromDBV3` во всех проектах.
- Для `ReadTable` реализована безопасная миграция контрактов: перенос `index_col` -> `partition_col` (если `partition_col` не задан по фактической семантике V2) и удаление `index_col`, чтобы исключить `Unknown input field` в V3.
- Добавлен обратный `downgrade`: переименование V3 -> V2, восстановление `index_col` для `ReadTable`, удаление V3-only полей (`max_rows_per_partition`, а также `limit`/`max_rows_per_partition` для `ReadQuery`).
- Добавлен расширенный набор unit-тестов `tests/unit/migrations/versions/test_0032_migrate_read_from_db_nodes_v2_to_v3.py` (11 кейсов) на преобразование контрактов, edge-cases (`const/var`, невалидный JSON), и массовую обработку нескольких нод в `upgrade/downgrade`.
- Проверка: `run_pytest` для `tests/unit/migrations/versions/test_0032_migrate_read_from_db_nodes_v2_to_v3.py` — 11 passed.

### 2026-03-03 18:07:28
- Доработана миграция `migrations/versions/0032_migrate_read_from_db_nodes_v2_to_v3.py`: теперь обновляется не только `name`, но и `display_name`.
- Логика для `display_name` сделана безопасной: переименование выполняется только если `display_name` совпадает с legacy-именем ноды (`ReadTableFromDBV2`/`ReadQueryFromDBV2` при upgrade и `ReadTableFromDBV3`/`ReadQueryFromDBV3` при downgrade), чтобы не затрагивать пользовательские переопределения.
- Обновлен SQL-апдейт миграции: в `graph_nodes` теперь сохраняются `name`, `display_name`, `input_values`.
- Расширены unit-тесты `tests/unit/migrations/versions/test_0032_migrate_read_from_db_nodes_v2_to_v3.py`: добавлены проверки условного обновления `display_name` для upgrade/downgrade и сохранения кастомных display-имен.
- Проверка: `tests/unit/migrations/versions/test_0032_migrate_read_from_db_nodes_v2_to_v3.py` — 11 passed; `tests/unit/migrations/versions` — 14 passed.

### 2026-03-03 18:10:50
- Уточнена логика миграции `migrations/versions/0032_migrate_read_from_db_nodes_v2_to_v3.py` для `display_name`: сравнение переведено на стандартные title-строки нод с пробелами (`Read Table From DB V2/V3`, `Read Query From DB V2/V3`), а не на технические class-name.
- Теперь `display_name` обновляется только когда он равен стандартному непереопределенному заголовку ноды; кастомные значения сохраняются.
- Добавлены/обновлены unit-тесты в `tests/unit/migrations/versions/test_0032_migrate_read_from_db_nodes_v2_to_v3.py`, включая кейс, подтверждающий что нестандартный `display_name` не изменяется.
- Проверка: `tests/unit/migrations/versions/test_0032_migrate_read_from_db_nodes_v2_to_v3.py` — 12 passed; `tests/unit/migrations/versions` — 15 passed.

### 2026-03-03 18:59:45
- Исправлена сборка прод-образа для обфускации конфигурации.
- В `docker/prod-builder.Dockerfile` удалено преждевременное удаление `config_prod.py`, из-за которого шаг подмены не создавал `config.so`.
- В `scripts/.ci/replace_builded_modules.py` усилена проверка ошибок (добавлены `raise` при отсутствии/множественности бинарников), добавлено удаление исходного файла при замене (`config.py` -> `config.so`) и изменено поведение при отсутствии исходного пути модуля: теперь выполняется попытка подмены по уже собранным бинарникам с предупреждением.
- Проверено пересборкой `prod-builder`: в `/app` присутствует `config.so`.

### 2026-03-03 19:04:13
- Уточнена схема сборки обфусцированного конфига для корректного импорта модуля.
- В `build_modules.toml` модуль `config` переключен с `config_prod.py` на `config.py` (без `module_to_replace`), чтобы Nuitka генерировал модуль с корректным именем и инициализатором.
- В `docker/prod-builder.Dockerfile` `config_prod.py` теперь копируется как `/app/config.py` на этапе компиляции.
- Проверено пересборкой: в образе есть `/app/config.so`, исходный `/app/config.py` отсутствует, `import config` выполняется успешно (loader: `nuitka_module_loader`).

### 2026-03-04 15:21:45
- Исправлена ошибка формирования `VALKEY_URL` в `config_prod.py`: добавлены корректные скобки в тернарном выражении, чтобы URL всегда включал хост/порт/БД при наличии пароля.
- Добавлен регрессионный unit-тест `tests/unit/test_config_prod.py` для проверки `VALKEY_URL`, `CELERY_BROKER_URL` и `CELERY_RESULT_BACKEND` в сценариях с паролем и без пароля.

### 2026-03-04 18:41:08
- Исправлена утечка Redis-клиентов в `services/task_worker/deps/pipeline_callbacks.py`: убран `ContextVar`, добавлен реюз клиента по event loop, очистка клиентов закрытых loop и функция `close_redis_clients()` для явного shutdown.
- В `services/task_worker/celery_app.py` добавлен вызов `close_redis_clients()` в `_shutdown` с логированием результата.
- Усилена устойчивость `src/runtime/async_loop_worker.py`: добавлена обработка аварийного завершения `run_forever`, гарантированный cleanup состояния, защита от рассинхронизации loop/thread и корректный restart при «мертвом» loop-потоке.
- Добавлены TODO-комментарии для архитектурного варианта 3 (вынос отправки событий в отдельный dispatcher с очередью, retry/backoff и backpressure).
- Добавлены и обновлены unit-тесты: `tests/unit/services/task_worker/deps/test_pipeline_callbacks.py`, `tests/unit/src/runtime/test_async_loop_worker.py`, `tests/unit/services/task_worker/test_celery_app.py`.

### 2026-03-04 19:54:26
- Исправлен `read_v3` для UUID-колонок: в `SQLReadExecutor` добавлен явный маппинг `ValueKind.UUID -> string`, из-за чего `build_meta` и чтение таблиц с `Nullable(UUID)` больше не падают.
- Улучшена диагностика ошибок типов: сообщения теперь содержат источник (таблица/запрос), имя колонки, `kind` и `type`.
- Добавлена ранняя валидация поддерживаемых output-kind в planner (`table`/`query`) с детализированными ошибками по колонкам.
- Обновлены и расширены unit-тесты `read_v3` для UUID и новых диагностических сообщений.

### 2026-03-04 20:20:09
- В узле `DataFrameGroupByAgg` добавлен точечный хотфикс для безопасного `reset_index` при конфликте имени индекса и колонки (ошибка вида `cannot insert <col>, already exists`).
- Для сброса индекса добавлен внутренний helper с переименованием конфликтующих индексных колонок в служебные имена.
- В коде оставлен `# TODO` про альтернативную стратегию: хранить колонку только в индексе без дублирования в `df.columns`, с пометкой о необходимости адаптации части нод.
- Добавлен unit-тест `test_groupby_agg_handles_index_column_name_conflict` для воспроизведения и проверки фикса.

### 2026-03-05 11:05:46
- Рефакторинг `src/node_dsl/base_node/df_output.py` под публичные callback-и форкнутого Dask (`add_callbacks`) с корректной sync->async связкой.
- Удален устаревший path через `_map_output/sync_map_output`, добавлены:
- - контекст партиции `DDFPartitionCallbackContext`;
- - потокобезопасный координатор lifecycle `start/end/error` для операций;
- - синхронные callback-обработчики с вызовом `async_worker.run(...)` только для async I/O сохранения партиций.
- Исправлены архитектурные проблемы новой версии:
- - убран `async def` в `on_partition` (теперь корутина не теряется);
- - исключен late-binding захват переменных цикла;
- - возвращен `progress_step` с lock-защитой от гонок;
- - добавлено предупреждение при `store_enabled=True` без cache/index managers.
- Добавлены регрессионные тесты `tests/unit/src/node_dsl/test_df_output_callbacks.py`:
- - проверка lifecycle/progress/cache на реальном `add_callbacks`-потоке;
- - проверка async bridge в partition callback.
- Проверка: `pytest tests/unit/src/node_dsl -q` -> `18 passed`.

### 2026-03-05 13:39:33
- Рефакторинг operation-callback пути для Dask/DVT:
- - В `src/node_dsl/base_node/df_output.py` переведена запись партиций на неблокирующую схему `async_worker.submit(...)` с координацией через `_PartitionStoreSubmitter` и ожиданием завершения перед `node_finished`.
- - Передача контекста в callback-и переведена с `partial(...)` на `metadata`, `operation_id` стабилизирован (убран суффикс `id(...)`).
- - Для DVT включены режимы callback-ов `copy_meta_mode="none"`, `copy_partition_mode="none"`, `partition_dispatch_mode="threaded"`.
- - Обновлены unit-тесты `tests/unit/src/node_dsl/test_df_output_callbacks.py` под новую async-модель (`submit + wait`).
- Проверка: целевые unit-тесты DVT по `df_output` успешно пройдены.

### 2026-03-05 23:11:01
- Перенесено исправление source-only callback-сценариев из временного обхода в `Visual_transformer` в библиотеку `dvt_dask`.
- В `dvt_dask` обновлена генерация задач в `dask_expr`: для `PartitionsFiltered` и `MapPartitions` теперь корректно прокидывается `op_meta`, включая случаи с `Alias`/`DataNode`.
- Добавлены регрессионные тесты в `dask/dataframe/dask_expr/tests/test_operation_callbacks.py` для `from_pandas`, `from_delayed(verify_meta=False)` и `map_partitions` с `add_callbacks`.
- В `Visual_transformer` удален хотфикс `_ensure_callback_emitting_ddf` из `DFOutputBaseNode`; поведение подтверждено unit-тестом `test_df_output_callbacks_for_source_only_expression`.

### 2026-03-06 11:42:17
- Добавлен unit-тест `tests/unit/src/node_dsl/test_df_output_callbacks_all_nodes.py` для проверки dask callback-ов на всех нодах `src/nodes`, наследованных от `DFOutputBaseNode`.
- Тест параметризован по автодискавери классов и для каждой целевой ноды создает две соседние ноды-наследники (`before`/`after`), после чего проверяет, что при compute целевой ноды callback-и (`on_process_start`, `on_process_success`, `on_progress_step`) срабатывают только у нее.
- Проверка выполнена локально: `pytest tests/unit/src/node_dsl/test_df_output_callbacks.py tests/unit/src/node_dsl/test_df_output_callbacks_all_nodes.py` (43 passed).

### 2026-03-06 11:52:03
- Уточнен тест `tests/unit/src/node_dsl/test_df_output_callbacks_all_nodes.py` по сценарию мини-пайплайна: ноды `_BeforeNeighborNode` и `_AfterNeighborNode` теперь выполняют собственные dask-трансформации (не passthrough).
- Целевая нода тестируется в цепочке `before -> target -> after`; callback-и собираются в общий журнал по всем нодам, после чего проверяется присутствие событий `start/finish/progress` для `before_node`, `target_node`, `after_node`, а также отдельные счетчики по каждой ноде.
- Добавлен явный compute для `before`, `target` и `after`, чтобы гарантированно получить callback-вызовы всех нод в мини-пайплайне.
- Проверка выполнена локально: `pytest tests/unit/src/node_dsl/test_df_output_callbacks.py tests/unit/src/node_dsl/test_df_output_callbacks_all_nodes.py` (43 passed).

### 2026-03-06 12:51:44
- Исправлена обработка отправки WebSocket-сообщений в `src/managers/websocket.py`: `send_sync` теперь пытается захватить текущий event loop при первом вызове и не выбрасывает `RuntimeError` при его отсутствии (сообщение логируется и пропускается).
- В `services/gateway/grpc/ws_forward_server.py` добавлена локальная обработка ошибок `ws_manager.send_sync`: `ForwardStream` больше не падает на единичной ошибке доставки, `ForwardUnary` возвращает `ForwardAck(ok=False, error=...)`.
- Добавлены unit-тесты: `tests/unit/src/managers/test_websocket.py` и `tests/unit/services/gateway/grpc/test_ws_forward_server.py` для сценариев отсутствия loop и ошибок отправки в контексте gRPC forward.

### 2026-03-06 13:18:26
- Отключено логирование в сервисную БД для dockerized тестов: в `docker/docker-compose.tests.yaml` для `tester_unit`, `tester_integration` и `tester_e2e` добавлен `LOG_TO_DB=false`, чтобы тестовые контейнеры не наследовали `LOG_TO_DB=true` из `.env`.
- В `tests/conftest.py` добавлена ранняя установка `os.environ["LOG_TO_DB"] = "false"` для глобального отключения DB sink в pytest-процессе и предотвращения попыток подключения к `127.0.0.1:15433` в unit/integration сценариях.

### 2026-03-06 16:52:00
- Исправлены dev-образы сервисов для корректного импорта модулей `services.*`: в Dockerfile сервисов добавлено явное копирование `services/__init__.py` в `/app/services/__init__.py`.
- Обновлены Dockerfile: `services/gateway/docker/dev.Dockerfile`, `services/orchestrator/docker/dev.Dockerfile`, `services/project_scheduler/docker/dev.Dockerfile`, `services/task_worker/docker/dev.Dockerfile`.
- В `services/task_benchmarking/docker/dev.Dockerfile` дополнительно исправлено копирование кода сервиса: вместо несуществующего `testing_services` теперь копируются `services/__init__.py` и `services/task_benchmarking`.
- Проведена проверка через `scripts/docker/build_dev.py` и `scripts/docker/deploy_dev.py`: контейнеры `gateway`, `orchestrator`, `task-worker`, `project-scheduler` запускаются и не падают с `ModuleNotFoundError: services.*`.

### 2026-03-10 15:29:46
- Выполнен рефактор WebSocket-сообщений: в рабочем коде проекта использование схем src.schemas.websocket заменено на схемы src.schemas.event (Event, EventType, EventBase и конкретные *Event модели).
- Обновлены сервисы gateway и orchestrator, клиенты ws_forward/gateway, менеджеры websocket/progress_bar, websocket log sink и unit-тесты для gRPC forward и WebSocketManager.
- В services/gateway/main.py OpenAPI-модели для websocket-потока переключены на Event/EventType.
- Проверка автотестами не выполнена: локальные Python-окружения .venv и .venv_py13 в текущем окружении неработоспособны (невозможно запустить pytest).

### 2026-03-03 18:59:45
- Исправлена сборка прод-образа для обфускации конфигурации.
- В `docker/prod-builder.Dockerfile` удалено преждевременное удаление `config_prod.py`, из-за которого шаг подмены не создавал `config.so`.
- В `scripts/.ci/replace_builded_modules.py` усилена проверка ошибок (добавлены `raise` при отсутствии/множественности бинарников), добавлено удаление исходного файла при замене (`config.py` -> `config.so`) и изменено поведение при отсутствии исходного пути модуля: теперь выполняется попытка подмены по уже собранным бинарникам с предупреждением.
- Проверено пересборкой `prod-builder`: в `/app` присутствует `config.so`.

### 2026-03-03 19:04:13
- Уточнена схема сборки обфусцированного конфига для корректного импорта модуля.
- В `build_modules.toml` модуль `config` переключен с `config_prod.py` на `config.py` (без `module_to_replace`), чтобы Nuitka генерировал модуль с корректным именем и инициализатором.
- В `docker/prod-builder.Dockerfile` `config_prod.py` теперь копируется как `/app/config.py` на этапе компиляции.
- Проверено пересборкой: в образе есть `/app/config.so`, исходный `/app/config.py` отсутствует, `import config` выполняется успешно (loader: `nuitka_module_loader`).

### 2026-03-04 15:21:45
- Исправлена ошибка формирования `VALKEY_URL` в `config_prod.py`: добавлены корректные скобки в тернарном выражении, чтобы URL всегда включал хост/порт/БД при наличии пароля.
- Добавлен регрессионный unit-тест `tests/unit/test_config_prod.py` для проверки `VALKEY_URL`, `CELERY_BROKER_URL` и `CELERY_RESULT_BACKEND` в сценариях с паролем и без пароля.

### 2026-03-04 18:41:08
- Исправлена утечка Redis-клиентов в `services/task_worker/deps/pipeline_callbacks.py`: убран `ContextVar`, добавлен реюз клиента по event loop, очистка клиентов закрытых loop и функция `close_redis_clients()` для явного shutdown.
- В `services/task_worker/celery_app.py` добавлен вызов `close_redis_clients()` в `_shutdown` с логированием результата.
- Усилена устойчивость `src/runtime/async_loop_worker.py`: добавлена обработка аварийного завершения `run_forever`, гарантированный cleanup состояния, защита от рассинхронизации loop/thread и корректный restart при «мертвом» loop-потоке.
- Добавлены TODO-комментарии для архитектурного варианта 3 (вынос отправки событий в отдельный dispatcher с очередью, retry/backoff и backpressure).
- Добавлены и обновлены unit-тесты: `tests/unit/services/task_worker/deps/test_pipeline_callbacks.py`, `tests/unit/src/runtime/test_async_loop_worker.py`, `tests/unit/services/task_worker/test_celery_app.py`.

### 2026-03-04 19:54:26
- Исправлен `read_v3` для UUID-колонок: в `SQLReadExecutor` добавлен явный маппинг `ValueKind.UUID -> string`, из-за чего `build_meta` и чтение таблиц с `Nullable(UUID)` больше не падают.
- Улучшена диагностика ошибок типов: сообщения теперь содержат источник (таблица/запрос), имя колонки, `kind` и `type`.
- Добавлена ранняя валидация поддерживаемых output-kind в planner (`table`/`query`) с детализированными ошибками по колонкам.
- Обновлены и расширены unit-тесты `read_v3` для UUID и новых диагностических сообщений.

### 2026-03-04 20:20:09
- В узле `DataFrameGroupByAgg` добавлен точечный хотфикс для безопасного `reset_index` при конфликте имени индекса и колонки (ошибка вида `cannot insert <col>, already exists`).
- Для сброса индекса добавлен внутренний helper с переименованием конфликтующих индексных колонок в служебные имена.
- В коде оставлен `# TODO` про альтернативную стратегию: хранить колонку только в индексе без дублирования в `df.columns`, с пометкой о необходимости адаптации части нод.
- Добавлен unit-тест `test_groupby_agg_handles_index_column_name_conflict` для воспроизведения и проверки фикса.

### 2026-03-10 16:32:10
- Добавлена миграция `migrations/versions/0035_migrate_env_vars_to_app_config.py` для переноса значений `LICENSE_KEY`, `DEFAULT_EMAIL`, `DEFAULT_PASSWORD` в `app_config`.
- В `upgrade()` реализовано заполнение только отсутствующих ключей и обновление только записей с `NULL`, без перезаписи уже заполненных значений.

### 2026-03-11 12:11:48
- В `.gitlab-ci.yml` добавлен stage `notify_merge` с job, который запускается только для merge-коммита и вызывает `scripts/.ci/send_b24_message.py` с путем из переменной окружения `B24_MESSAGE_MERGE_TOML`.
- В job добавлена подготовка переменных с автором merge и именами исходной и целевой веток.
- Обновлен шаблон `trash/merge_message.toml`: сообщение теперь явно сообщает о merge, кто его выполнил и из какой ветки в какую он был сделан.

### 2026-03-10 16:25:12
- В схему src/schemas/event/node_execution_status.py добавлено опциональное поле message для передачи текста ошибки узла.
- В services/task_worker/deps/pipeline_callbacks.py callback on_node_error теперь отправляет NodeExecutionStatusEvent со status=ERROR и message из исключения.
- В services/orchestrator/deps/worker_event_callbacks.py при пересылке NodeExecutionStatusEvent в websocket-forward добавлена передача message=event.message.
- Добавлен unit-тест test_on_node_error_sends_error_message_in_node_execution_status_event в tests/unit/services/task_worker/deps/test_pipeline_callbacks.py.

### 2026-03-10 17:10:59
- В services/task_worker/deps/pipeline_processor.py отправка node-статусов (on_node_process_start/on_node_process_success/on_node_error) переведена из ветки FULL в общий блок send_ws_messages, чтобы события NODE_EXECUTION_STATUS отправлялись и в режиме METADATA_ONLY.
- Добавлен unit-тест tests/unit/services/task_worker/deps/test_pipeline_processor.py, проверяющий подключение node status callback-ов для METADATA_ONLY.

### 2026-03-11 15:19:28
- В core/mapper/factory/_db_columns.py изменена логика формирования PK: если primary_key_cols не передан, первичный ключ больше не выставляется автоматически по DBColumn.primary_key.
- Добавлено пояснение в docstring build_table_from_db_columns, что PK применяется только при явной передаче primary_key_cols.
- Обновлены тесты tests/unit/core/mapper/test_factory_db_columns.py: зафиксировано отсутствие PK без primary_key_cols, добавлен кейс явного PK и обновлена проверка ошибки для nullable PK при явном primary_key_cols.

### 2026-03-11 16:08:00
- В core/mapper/factory/_db_columns.py исправлена нормализация имен: ASCII-колонки теперь сохраняют исходный регистр (например, Period), не-ASCII по-прежнему транслитерируются в lower-case ASCII.
- Для колонок включено явное quoting (quote=True), чтобы DDL для PostgreSQL/Oracle/других SQL-диалектов сохранял регистр идентификаторов.
- В ClickHouse-ветке сборки MergeTree строковые идентификаторы переведены с text(...) на SQLAlchemy identifier expressions, чтобы order_by/primary_key корректно работали с case-sensitive именами.
- Добавлен регрессионный тест tests/unit/core/mapper/test_factory_db_columns.py на сохранение case для колонки Period и проверку квотирования в DDL PostgreSQL/Oracle.

### 2026-03-11 16:24:00
- В core/mapper/factory/_db_columns.py исправлен Oracle-маппинг строковых типов для DDL из metadata: STRING/CATEGORY/OBJECT/DICTIONARY теперь компилируются в VARCHAR2(4000), чтобы исключить генерацию невалидного VARCHAR2 без длины.
- В tests/unit/core/mapper/test_factory_db_columns.py усилен регрессионный тест: для колонки Period дополнительно проверяется, что Oracle DDL содержит "Period" VARCHAR2( с явной длиной типа.

### 2026-03-11 16:38:00
- В services/gateway/routes/utils/create_table.py для generate-table-ddl добавлена диалектная нормализация nullable: в ClickHouse все колонки принудительно NOT NULL, в остальных диалектах колонки помечаются NULLABLE (кроме явно заданных PK).
- В generate-table-ddl восстановлена передача primary_key_cols в build_table_from_db_columns после вычисления PK из index_col/metadata.
- Добавлены unit-тесты tests/unit/services/gateway/routes/utils/test_create_table_ddl_schema_resolution.py на нормализацию nullable и передачу primary_key_cols в фабрику таблицы.

### 2026-03-11 12:20:47
- Исправлен trigger job `notify_merge` в `.gitlab-ci.yml`: вместо `CI_COMMIT_MESSAGE` используется `CI_COMMIT_TITLE`, чтобы job корректно появлялся для merge-коммитов с многострочным сообщением.
- Также разбор исходной и целевой веток в shell-скрипте переведен на `CI_COMMIT_TITLE`, чтобы соответствовать фактическому формату merge-коммита GitLab.

### 2026-03-11 12:26:12
- Исправлена подстановка переменных окружения в `scripts/.ci/send_b24_message.py`: выражения вида `${VAR:-default}` теперь используют `default`, если переменная не задана или пуста, как в shell.
- В `.gitlab-ci.yml` job `notify_merge` переведен на POSIX-совместимый разбор merge-коммита через `sed` вместо bash-специфичного `[[ ... =~ ... ]]`, а источник автора merge дополнен fallback до `CI_COMMIT_AUTHOR`.

### 2026-03-11 12:40:08
- В `.gitlab-ci.yml` добавлен общий шаблон `after_script` для B24-уведомлений по job-статусу и подключен к stage'ам `build`, `unit_tests`, `deploy_dev`, `integration_tests`, `e2e_tests`, `publish_images`, `deploy_preprod`, `deploy_prod`.
- Для каждого из этих job'ов добавлены отдельные TOML-конфиги в `trash/b24_messages`.
- Сообщения теперь формируются с разными эмодзи и текстом для успешного и неуспешного завершения через переменные `B24_STATUS_ICON` и `B24_STATUS_TEXT`.

### 2026-03-11 14:47:53
- Для merge-уведомления добавлено обогащение данными MR через GitLab API: новый скрипт `scripts/.ci/export_merge_request_metadata.py` получает автора MR, пользователя, выполнившего merge, а также source/target branch.
- В `notify_merge` добавлен вызов этого скрипта с fallback на текущие значения из окружения.
- Обновлен шаблон `.ci/b24_messages/merge_message.toml`: теперь сообщение содержит отдельные поля `MR создал` и `Merge выполнил`.

### 2026-03-11 16:52:40
- Обновлен `.gitlab-ci.yml` под новый release-поток: после `integration_tests` добавлено B24-уведомление и отложенный на 10 минут деплой `preprod`, после успешных `e2e_tests` добавлено B24-уведомление и одновременный отложенный на 10 минут деплой `demo` и `prod`.
- Добавлены шаблоны сообщений B24 для предупреждений об обновлении `preprod`, совместного обновления `demo` и `prod`, а также уведомления о результате деплоя `demo`.
- Исправлен `deploy_demo`: добавлена переменная лицензии, логирование в артефакт и перевод в автоматический delayed deploy через общий stage `deploy_release`.

### 2026-03-11 17:01:27
- Скорректирован release-поток в `.gitlab-ci.yml`: `e2e_tests` больше не ждут `deploy_preprod`, а запускаются после `publish_images` и уведомления о предстоящем обновлении `preprod`, что позволяет выполнять `e2e` параллельно 10-минутному ожиданию delayed-деплоя `preprod`.
- Усилены зависимости для `demo` и `prod`: уведомление о предстоящем обновлении и сами delayed-деплои теперь требуют одновременно успешного `deploy_preprod` и успешных `e2e_tests`.
- Обновлены сообщения в `e2e_tests`, чтобы отражать запуск на отдельном стенде `DVT-e2e-tests-stand`, а не на `preprod`.

### 2026-03-11 18:46:05
- Оптимизированы интеграционные тесты в `tests/integration`.
- В фикстурах БД убран полный `drop_all/create_all` на каждый тест: схема теперь поднимается один раз, а изоляция тестов сохраняется через outer transaction и `SAVEPOINT`.
- Переработаны gateway-фикстуры: bootstrap приложения и HTTP-клиента переиспользуется между тестами, `flushall()` удален, для store-тестов добавлена изоляция ключей по уникальному префиксу.
- Сокращена стандартная SQL-матрица `read_v3`: по умолчанию запускаются `postgres/mysql/clickhouse`, полный набор `mssql/oracle` оставлен за флагом `DVT_TEST_FULL_DB_MATRIX`.
- Из helper-ов `read_v3` убран лишний предварительный `DROP TABLE` при уникальных именах таблиц.
- Устаревшие интеграционные тесты `read_v2` удалены.
- Убраны медленные fixed sleep/polling: из Celery-теста удален стартовый `sleep`, TTL-проверка в store переведена на короткий bounded polling, а ClickHouse write-тесты используют короткий retry helper вместо ожиданий до 5 секунд.
- Redis cache/index cleanup в нескольких интеграционных тестах заменен на закрытие клиентов без полного сканирования ключей.

### 2026-03-11 18:56:48
- Добавлен локальный скилл `git-tag-changelog` в `.codex/skills`.
- Скилл подготавливает контекст для changelog между git-тегами: определяет текущий и предыдущий теги, сохраняет `diff.txt`, `changed_files.txt` и `prompt.md` в `tmp/changelog-context/<tag>/`.
- Добавлен скрипт `prepare_changelog_context.py` без рекурсивного вызова `codex`, чтобы сам агент использовал подготовленные артефакты при написании changelog.

### 2026-03-11 19:59:31
- Сформирован подробный changelog по изменениям между тегами `1.10.5` и `1.10.6`.
- Результат сохранен в файл `tmp/changelog.txt`.

### 2026-03-11 19:59:31
- Сформирован файл `tmp/changelog.txt` с changelog для версии `1.10.6` на основе diff между тегами `1.10.5` и `1.10.6`.
- Изменения сгруппированы по категориям и описаны на понятном русском языке.

### 2026-03-11 20:20:59
- Добавлен stage `write_changelog` в `.gitlab-ci.yml` для теговых пайплайнов после `notify_merge`.
- Новый job запускает `scripts/.ci/run_codex.py` с конфигурацией `.ci/codex/write_changelog.toml`, сохраняет diff и сгенерированный changelog в артефакты и отправляет changelog в Bitrix24 через новый шаблон `.ci/b24_messages/changelog_message.toml`.

### 2026-03-11 20:26:59
- Обновлен job `write_changelog_b24` в `.gitlab-ci.yml` для включения изменений сабмодулей в diff для Codex.
- Добавлены рекурсивная инициализация и fetch сабмодулей, а команда формирования diff переведена на `git diff --submodule=diff`.

### 2026-03-11 20:39:42
- Исправлен `scripts/.ci/run_codex.py`: теперь при наличии `output_path` скрипт сохраняет последний итоговый ответ Codex во внешний файл сам, без требования записи из среды `codex exec`.
- Обновлен конфиг `.ci/codex/write_changelog.toml`: Codex теперь должен вернуть только готовый changelog текстом, а сохранение в `${CHANGELOG_PATH}` выполняет Python-обертка.

### 2026-03-11 21:42:14
- Добавлен автоматический анализ падений test job в `.gitlab-ci.yml` для `unit_tests`, `integration_tests` и `e2e_tests`.
- Тестовые job теперь сохраняют логи в `tmp/ci-test-reports`, а `after_script` при статусе `failed` запускает Codex по конфигу `.ci/codex/test_failure_analysis.toml` и отправляет отдельный отчет в Bitrix24 через шаблон `.ci/b24_messages/test_failure_analysis_message.toml`.

### 2026-03-11 23:20:52
- Обобщена CI-механика разбора падений job'ов в `.gitlab-ci.yml`: вместо `TEST_*` введены нейтральные переменные `FAILURE_ANALYSIS_*`, добавлен общий шаблон `.critical_failure_analysis` и подключен лог-сбор для критичных job'ов `build`, `unit_tests`, `deploy_dev`, `integration_tests`, `publish_images`, `deploy_preprod`, `e2e_tests`, `deploy_demo`, `deploy_prod`.
- Переименованы и обновлены TOML-конфиги Codex и Bitrix24 для общего разбора падений job'ов: добавлены `.ci/codex/job_failure_analysis.toml` и `.ci/b24_messages/job_failure_analysis_message.toml`, удалены старые test-специфичные шаблоны.

### 2026-03-12 12:11:13
- Добавлен новый пакет `core/db/write_v3` со строгим typed API для записи в БД: модели запросов/плана/результата, иерархия ошибок, planner, resolver, bounded Dask-обработка, SQL- и ClickHouse-executor'ы для режимов `append`, `truncate`, `upsert`.
- Добавлена новая backend-нода `WriteDataFrameToDBV3` и экспорт в `src/nodes/write/__init__.py`.
- Добавлены unit-тесты для `write_v3` и ноды `WriteDataFrameToDBV3`, покрывающие resolver, SQLite `append/upsert` с дубликатами и `NULL`, а также node-level сценарий `upsert`.

### 2026-03-12 13:39:02
- Рефакторинг DDL-утилит Gateway перенесен в пакет `services/gateway/routes/utils/DDL`.
- Эндпоинт `POST /utils/create-table` переведен на discriminated union-контракт по полю `mode` со значениями `from_schema` и `from_sql`, а старый модуль `services/gateway/routes/utils/create_table.py` оставлен как совместимый shim с реэкспортом.
- Добавлены роуты `POST /utils/ddl/create-database`, `POST /utils/ddl/create-schema` и `POST /utils/ddl/generate-schema-ddl`.
- Расширены Pydantic-схемы запросов/ответов для DDL-операций и добавлено общее исключение `DDLError`.
- Обновлены unit-тесты для нового контракта `/utils/create-table` и добавлены тесты для DDL-роутов базы и схемы.

### 2026-03-12 16:21:03
- Вынесена DDL-логика создания БД, схем и таблиц из `core/db/write_v3` в новый пакет `core/db/ddl`.
- `write_v3` переведен в strictly write-only режим: удалены typed/raw DDL из `WriteRequest`, planner теперь требует существующую таблицу, а `WriteDataFrameToDBV3` больше не принимает DDL-поля.
- Gateway DDL routes переведены на новый `core/db/ddl`, `core/db/ddl_utils.py` оставлен как совместимый shim для generic helper-ов и re-export перенесенных функций.
- Обновлены unit tests для нового контракта записи и DDL-слоя.

### 2026-03-12 16:26:27
- Роуты `services/gateway/routes/utils/DDL` переведены на прямое использование `core/db/ddl` без импорта `core/db/ddl_utils`.
- В `core/db/ddl` добавлен модуль `engine.py` с `build_engine` и `build_engine_from_metadata`, а `core/db/ddl/__init__.py` расширен экспортом engine-builder API.
- `core/db/ddl_utils.py` переведен в роль shim-слоя с реэкспортом функций из `core/db/ddl`; gateway DDL tests обновлены и подтверждают новый источник DDL-логики.

### 2026-03-12 16:47:41
- Расширен `core/db/ddl` контракт для ClickHouse: `ClickHouseEngineSpec` переведен на строгий `Literal` по поддерживаемым engine family и дополнен полями `sample_by`, `ttl_expression`, `version_column`, `sign_column`, `summing_columns`, `table_path`, `replica_name`, а также детальной валидацией обязательных/запрещенных параметров.
- В `core/db/ddl/table.py` добавена сборка typed ClickHouse engine через `clickhouse_sqlalchemy.engines`, поддержка `TableCreateSpec` в генерации DDL и в создании таблиц из схемы, включая индексы в SQL DDL output.
- HTTP-схемы и роуты `services/gateway/routes/utils/DDL/table.py` расширены полем `table_create_spec` для `CreateTableFromSchemaRequest` и `GenerateTableDDL`; новые фичи покрыты unit tests для моделей DDL и gateway routes.

### 2026-03-12 19:27:38
- Исправлен `core/db/write_v3`: убран по-partition `compute()` из Dask write helper.
- Запись partition-ов переведена на единый `DataFrame/Series.compute()` через `map_partitions`, чтобы сохранить корректный lifecycle public operation callbacks из `dvt_dask`.
- Добавлены регрессионные unit-тесты для helper-а `write_v3`, SQLite write path и ноды `WriteDataFrameToDBV3` на сценарий с upstream `add_callbacks(...)`.

### 2026-03-12 19:34:03
- В `core/db/write_v3` добавлена фильтрация служебных колонок с префиксом `__dvt_` перед валидацией и записью в SQL/ClickHouse executors.
- Это закрывает падение `WriteDataFrameToDBV3` на внутренних полях вроде `__dvt_partition_bucket`, приходящих из `read_v3` и других runtime-пайплайнов.
- Добавлены unit-тесты на SQL append и ClickHouse normalize path для сценариев со служебными колонками.

### 2026-03-12 21:35:58
- Переведен `scripts/.ci/build_modules.py` с TOML-конфига на CLI-аргументы `--name`, `--module`, `--include-package`, `--output-dir`, `--jobs` с автоматическим расчетом `nproc - 1`.
- Перестроен `docker/prod-builder.Dockerfile`: добавлены отдельные Nuitka-stage для `core`, `node_dsl`, `pipeline`, `license`, `config`, интегрирован `ccache`, замена исходников на бинарники перенесена в Dockerfile.
- В production publish path добавлен сервис `project-scheduler` в `docker/docker-compose.prod.override.yaml`.
- Удалены устаревшие файлы `build_modules.toml` и `scripts/.ci/replace_builded_modules.py`.

### 2026-03-16 11:56:54
- Исправлено определение обязательных полей в `src/models/app_config.py`: поля с `default_factory` больше не считаются обязательными.
- Добавлены unit-тесты для `AppConfig` и вспомогательных функций в `tests/unit/src/models/test_app_config.py`, включая сценарии загрузки, заполнения и сохранения конфигурации через мок-сессии.

### 2026-03-16 12:06:37
- Исправлен маршрут `services/gateway/routes/app_config/crud.py`: сохранение значения конфигурации по ключу теперь корректно ожидает `preserve_database`.
- Добавлены unit-тесты для маршрутов `app_config` в `tests/unit/services/gateway/routes/app_config/test_crud.py` и `tests/unit/services/gateway/routes/app_config/test_misc.py` с проверкой CRUD-сценариев, обязательных полей и списка незаполненных обязательных полей.

### 2026-03-16 12:37:12
- Исправлена сериализация ответов маршрутов `services/gateway/routes/app_config/crud.py`: `AppConfigReadSchema.model_construct` теперь вызывается с распакованным `model_dump()`, чтобы ответ включал все поля конфигурации.
- Обновлены ожидания в `tests/unit/services/gateway/routes/app_config/test_crud.py` под текущую реализацию маршрутов без `refresh()`.

### 2026-03-16 14:07:39
- Исправлено логирование `services/task_worker` в БД для `prefork`-режима: main-process теперь поднимает отдельный DB sink, поэтому startup/shutdown/heartbeat логи воркера тоже сохраняются в таблицу `logs`.
- В `worker_process_init` добавен сброс унаследованного main-process DB sink в child-процессе, чтобы дочерние Celery worker-процессы лениво создавали собственные sink без fork-наследованных хендлеров.
- В `services/task_worker/tasks/worker_tasks.py` инициализация log sink перенесена в самое начало task/control entrypoint, чтобы уменьшить потерю ранних логов до старта выполнения задачи.
- Добавлены unit-тесты на main-process DB sink для prefork и на очистку унаследованного sink в child-процессе; таргетные тесты `tests/unit/services/task_worker/test_celery_app.py` и `tests/unit/services/task_worker/tasks/test_worker_tasks.py` проходят.

### 2026-03-16 14:17:48
- Устранен регресс после изменений логирования `services/task_worker`: откатана инициализация DB sink в `MainProcess` для `prefork`, а также сброс унаследованного sink в child-процессе, так как этот путь влиял на прием задач воркером.
- Сохранена безопасная часть изменения: `ensure_log_sinks_for_task_process()` по-прежнему вызывается в самом начале `handle_task` и `handle_task_control`, чтобы child-процесс поднимал DB/WS sink до основной логики задачи.
- Повторно проверены unit-тесты `tests/unit/services/task_worker/test_celery_app.py` и `tests/unit/services/task_worker/tasks/test_worker_tasks.py` — проходят.
- После рестарта сервиса подтверждено на реальном рантайме, что `task_worker` снова принимает и выполняет задачи: обработаны metadata-задачи `bc6840da-1ccb-47f9-914b-74497ad2f2f1` и `87889914-ce93-45b1-b3c2-e96441b44313`, их логи записаны в БД.

### 2026-03-16 14:55:53
- Переработано логирование `task_worker` для Celery child-процессов.
- - В `services/task_worker/celery_app.py` добавлен multiprocess log bridge: child-процесс теперь сначала пытается отправлять структурированные логи в `MainProcess`, а `MainProcess` владеет DB/WS sink и listener'ом.
- - Добавлен fallback на локальные sink'и child-процесса с обязательным `logger.complete()` и финализацией в конце `handle_task/handle_task_control`, чтобы не терялся хвост логов и traceback перед recycle child-процесса.
- - В `src/logger/_multiprocessing/*` улучшен перенос traceback и метаданных: child sink использует `sink_formatter`, bridge сохраняет `traceback_str`, parent listener восстанавливает `name/module/function/line/time` и не дублирует traceback в `message`.
- - Добавлены unit-тесты для финализации логирования `task_worker`, вызова финализации после обработки задачи и re-emit traceback через parent listener.

### 2026-03-16 18:56:09
- Добавлена миграция `0036_add_roles_and_migrate_users_role.py`.
- Создана таблица `roles`, добавлено заполнение ролями из `DefaultRoles`, выполнен перенос пользователей с `users.is_admin` на `users.role` и добавлен downgrade обратно.
- Добавлен unit-тест на преобразование ролей в `tests/unit/migrations/versions/test_0036_add_roles_and_migrate_users_role.py`.

### 2026-03-16 19:10:23
- Обновлена миграция `0036_add_roles_and_migrate_users_role.py`.
- Добавлено чтение `app_config.default_email`: если пользователь с таким email найден, ему назначается роль `superadmin` при переносе на `users.role`.
- Обновлен unit-тест миграции для проверки назначения `superadmin` и обратного преобразования в `is_admin`.

### 2026-03-16 19:24:49
- Переведен backend-код с legacy-проверок `is_admin` на role-based доступ через общие helper-функции.
- Обновлены gateway routes/deps, CRUD пользователей, служебные скрипты и `dvt_mcp`: вместо булевого флага используется поле `role` и проверка привилегированных ролей `admin/superadmin`.
- Обновлены backend-схемы и тестовые фикстуры: admin API и создание пользователей теперь работают с полем `role`, а unit/integration/e2e тестовые данные больше не используют `is_admin`.

### 2026-03-17 16:52:51
- Добавлена отдельная backend-подсистема первичной инициализации: реализованы `SetupManager`, HTTP-схемы setup и новые маршруты `services/gateway/routes/setup.py` с агрегированным статусом и bootstrap-операциями для первого `superadmin` и bootstrap-полей `AppConfig`.
- `superadmin_email` и `superadmin_password` удалены из `src/models/app_config.py`; `AppConfig` теперь хранит только runtime-конфиг и умеет отдельно вычислять bootstrap-required поля через `bootstrap_required_fields()` и `bootstrap_unfilled_fields()`.
- Маршруты `app-config` переведены на обычную admin-аутентификацию без специального режима "незаполненного конфига", удалён устаревший маршрут `services/gateway/routes/superadmin.py`, обновлены unit-тесты.
- Для фоновых сервисов и `dvt_mcp` добавлен resolver системного пользователя с приоритетом `config.SECURITY.DEFAULT_EMAIL` и fallback на первого активного привилегированного пользователя; документация `AGENTS.md` и описание инструмента `run_task` синхронизированы с новым поведением.

### 2026-03-17 18:08:22
- Удалены `config.SECURITY.DEFAULT_EMAIL` и `config.SECURITY.DEFAULT_PASSWORD` из `config.py` и `config_prod.py`.
- Фоновые сервисы (`dcc_manager`, `project_scheduler`) и `dvt_mcp` переведены на выбор первого активного привилегированного пользователя без привязки к default email; ответ `run_task` теперь возвращает `service_user_email`.
- Из `install.sh`, `docker-compose.yaml` и `docker/docker-compose.ycm.yaml` убраны `DVT_DEFAULT_EMAIL` и `DVT_DEFAULT_PASSWORD`, чтобы bootstrap первого superadmin больше не выглядел как env-конфигурация.
- E2E-фикстура `tests/e2e/fixtures/gateway_e2e_runtime.py` больше не использует default credentials из `config` и при необходимости поднимает первого superadmin через `/api/setup/superadmin`.
- Добавлены unit-тесты `tests/unit/src/crud/test_admin_db.py` на resolver системного пользователя.

### 2026-03-18 12:47:09
- Добавлена модель `Organization` и миграция `0037_add_organizations_and_acl_scope.py` с backfill существующих данных в дефолтную организацию.
- Обновлены модели, CRUD, setup bootstrap и проверки доступа: `user` видит только свои сущности в своей организации, `admin` видит все сущности своей организации, `superadmin` имеет глобальный доступ.
- Перенесены gateway-маршруты `db_connections` на локальную реализацию с новым ACL, добавлен шаг bootstrap `organization`, обновлены фикстуры и unit-тесты под `organization_id`.

### 2026-03-18 12:58:16
- Переведено представление ACL scope с сырых словарей на dataclass `AccessScope` в `src/utils/access_control.py`.
- Обновлены все вызовы `get_access_scope` на использование атрибутов dataclass вместо индексного доступа по строковым ключам.
- Проверены синтаксис и unit-тесты для setup, graph/dataframe routes и websocket forward после замены.

### 2026-03-18 13:20:05
- Рефакторинг `src/crud/admin_db.py` выполнен в пакет `src/crud/admin/user` по паттерну остальных CRUD-модулей.
- Добавлены CRUD-файлы `create.py`, `read.py`, `update.py`, `delete.py` с основным read-entrypoint `get_users_by(...)`, а `commit` вынесен из CRUD на уровень caller.
- Переведены импорты в gateway admin user route, `services/dvt_mcp`, `project_scheduler` и `dcc_manager`; старый `src/crud/admin_db.py` удален.
- Добавлены unit-тесты для нового admin user CRUD в `tests/unit/src/crud/admin/user`.

### 2026-03-18 13:28:14
- Исправлен порядок операций в миграции `0037_add_organizations_and_acl_scope.py`.
- В `upgrade()` перенос старых graph/subgraph foreign key на `projects(id, organization_id)` теперь выполняется до удаления `unique_project_id_user_id`.
- В `downgrade()` восстановление старого unique и foreign key также переставлено в корректный порядок, чтобы избежать ошибок зависимостей PostgreSQL.

### 2026-03-18 15:12:56
- Реализован DSL-реестр шагов первичной инициализации в `src/setup/dsl` и добавлены классы шагов в `src/setup/steps` для `organization`, `superadmin` и `app_config`.
- `SetupManager` и `services/gateway/routes/setup.py` переведены на динамическую регистрацию шагов и единый submit-контракт `POST /setup/{code}` с телом `values`, а `GET /setup/status` теперь возвращает расширенные метаданные шагов и полей.
- Обновлены unit-тесты setup-слоя и e2e bootstrap-фикстура, чтобы использовать новый status-driven flow без хардкода старых setup-эндпоинтов.

### 2026-03-18 16:03:31
- Убран `SetupManager`: orchestration и query API первичной инициализации перенесены в публичный модуль `src/setup/api.py` и реэкспортированы через `src/setup`.
- `BaseSetupStep` и шаги в `src/setup/steps` переведены на classmethod-интерфейс и теперь используют `src.setup` helper-функции напрямую без manager-объекта.
- `services/gateway/routes/setup.py` и unit-тесты setup-слоя обновлены на прямое использование `src.setup`, а старые manager-ориентированные тесты и файл `src/managers/setup.py` удалены.

### 2026-03-18 20:32:40
- Исправлена ORM-модель `DBConnection`: поле `connection_properties` переопределено с конкретным union-типом, чтобы корректно проходить валидацию `SQLModel`/`Pydantic` при создании соединений в Gateway и интеграционных тестах.
- Обновлен интеграционный тест `task_worker`: добавлено создание организации и обязательные `organization_id` для `User`, `Project` и `Task` в соответствии с актуальной многотенантной моделью данных.
- Подтвержден полный зеленый прогон интеграционных тестов: `143 passed`.

### 2026-03-19 11:40:16
- Добавлен новый CRUD-пакет `src/crud/organization` для чтения, создания, обновления и удаления организаций с проверкой уникальности `inn` и зависимостей перед удалением.
- Добавлены HTTP-схемы `src/schemas/http/organization.py` и новый router `services/gateway/routes/organization`, подключенный в `services/gateway/main_router.py` под `/organizations` с ACL по ролям `superadmin/admin/user`.
- Добавлены unit-тесты для CRUD и gateway routes организаций, покрывающие доступ по ролям, конфликт по `inn`, запрет удаления своей организации и запрет удаления организаций с зависимостями.

### 2026-03-19 14:01:37
- Добавлены модули `exceptions.py` для CRUD-сущностей в `src/crud`: `admin/user`, `organization`, `project`, `queue_topic`, `task`, `graph`, `graph_nodes`, `graph_edges`, `subgraphs`.
- Для новых внутренних исключений введены отдельные категории `CRUD_*` в `src/exception_registry/exception_types.py`, чтобы разделить domain/CRUD-ошибки и будущие gateway HTTP-ошибки.
- `src/crud/organization` переведен на новый модуль исключений с сохранением обратной совместимости через `errors.py`, обновлены package exports в `__init__.py`.

### 2026-03-19 15:32:45
- Обновлены unit-тесты для CRUD организаций и реестра исключений под новые классы исключений и текущее поведение gateway auth dependencies.
- Исправлен `RegisteredHTTPException`: в базовый `HTTPException` теперь передается вычисленный `detail`, поэтому class-level `detail` корректно сохраняется.
- Добавлены `__init__.py` в каталоги `tests/unit/services/gateway/routes/organization` и `tests/unit/services/gateway/routes/queue_topic`, чтобы устранить конфликт коллекции pytest для файлов `test_crud.py`.

### 2026-03-19 17:47:02
- Реализовано batch-удаление проектов в `services/gateway/routes/project/crud.py` с сохранением проверок доступа и soft-delete.
- Для запроса со смешанным набором ID теперь удаляются найденные доступные проекты, а отсутствующие/недоступные перечисляются в сообщении ответа.
- Для delete-маршрутов исправана обработка кейса `not found`: возвращается корректный HTTP 404 без падения на обертке registry-исключений.
- Добавлены unit-тесты на частичное batch-удаление и на 404, когда доступных проектов нет.

### 2026-03-19 18:32:24
- Маршрут копирования проекта `services/gateway/routes/project/copy.py` переведен с `sqlmodel.Session.exec()` на SQLAlchemy-стиль через `session.execute(...)`.
- Это устранило падение FastAPI-маршрута при использовании `Depends(get_session)`, который возвращает `sqlalchemy.orm.Session` без метода `exec()`.
- Проверен unit-тест `tests/unit/services/gateway/routes/project/test_copy.py`: 3 теста проходят.

### 2026-03-20 15:01:24
- В `src/types/constants.py` добавлен токен `EMPTY_STRING_VALUE = "__dvt_empty_string_value"` и экспортирован в `src/types/__init__.py`.
- В ноде `src/nodes/transform/df_filter.py` добавлена поддержка токена пустой строки: `empty_string_literal_token` в `filter_rules_spec` и нормализация `__dvt_empty_string_value -> ""` в `_normalize_literal`.
- Расширены unit-тесты `tests/unit/src/nodes/transform/test_df_filter.py`: проверены кейсы сравнения `==` и `isin` с токеном пустой строки.

### 2026-03-19 16:06:07
- В `trash/pytest_mon` добавлен класс `PytestMonitorRouter`, наследующий `fastapi.APIRouter`, для мониторинга тестового каталога через HTTP.
- Реализованы endpoint'ы `/fixtures` и `/tests`, которые возвращают имя, исходный код, сигнатуру, docstring и расположение pytest-фикстур и тестов.
- Добавлено AST-сканирование без импорта модулей и инкрементальный кеш по размеру и времени изменения файлов.
- Добавлены unit-тесты на извлечение фикстур/тестов и инвалидaцию кеша при изменении файлов.

### 2026-03-19 18:19:50
- Добавлен пример скрипта `tmp/create_organization_and_first_admin_via_api_key.py`.
- Скрипт создает организацию через `POST /api/organizations` и первого admin-пользователя через `POST /api/admin/user`, используя заголовок `X-API-Key`.
- Добавлены параметры CLI и переменные окружения для base URL, API key, данных организации и admin-пользователя.

### 2026-03-19 18:23:41
- Упрощен пример скрипта `tmp/create_organization_and_first_admin_via_api_key.py`.
- Убраны CLI-параметры и сложная структура, оставлены простые константы в начале файла и последовательные запросы к API.
- Текст комментариев и сообщений в скрипте переведен на русский для более простого использования.

### 2026-03-20 14:19:32
- В `.gitlab-ci.yml` добавлен общий шаг создания дампа PostgreSQL перед деплоем.
- Дампы сохраняются в `tmp/postgres-dumps/` и публикуются в GitLab artifacts для job `deploy_dev`, `deploy_preprod`, `deploy_demo` и `deploy_prod`.
- Для install-based стендов бэкап читает текущие параметры БД из `/var/lib/dvt/.env`, для dev используется контейнер `DVT_postgres`.

### 2026-03-20 14:50:20
- Унифицированы переменные PostgreSQL в `.gitlab-ci.yml`: удалены варианты `DVT_PG_*`, оставлены только `DVT_POSTGRES_USER`, `DVT_POSTGRES_PASSWORD`, `DVT_POSTGRES_DB`.
- Обновлены ссылки на CI-переменные для dev/prod стендов на формат `DVT_*_POSTGRES_*`.
- Во всех `docker-compose` файлах имена контейнеров приведены к виду `dvt-{контейнер}`, включая dev и test окружения.

### 2026-03-20 14:52:52
- Из `.gitlab-ci.yml` удалена переменная `DVT_POSTGRES_CONTAINER_NAME` как избыточная после унификации имен контейнеров.
- Шаг резервного копирования PostgreSQL теперь использует единое имя контейнера `dvt-postgres` без job-специфичных переопределений.

### 2026-03-23 16:42:05
- Добавлен подробный план реализации `HARD_STOP` и `OOM_GUARD` без возврата к отдельному subprocess.
- План сохранен в `tmp/task-hard-stop-oom-guard-plan.md` и описывает telemetry активных task-процессов, execution registry в orchestrator, reconciler терминальных статусов и поэтапное внедрение.

### 2026-03-23 19:05:00
- Реализован новый lifecycle для `HARD_STOP`: активные задачи переводятся в `CANCEL_REQUESTED`, а финализация в `CANCELLED`/`ERROR` перенесена в orchestrator-side supervisor.
- Добавлены `TaskExecutionTelemetryEvent`, execution registry и `TaskExecutionSupervisor` в orchestrator для отслеживания RSS активных task-процессов и выбора жертвы OOM guard по фактическому потреблению памяти.
- В task worker добавлена отправка telemetry из процесса выполнения задачи и защита от старта задач со статусом `CANCEL_REQUESTED`; `STOP` и `HARD_STOP` сведены к одному hard-stop поведению.
- Добавлена миграция `0039_add_task_termination_reason.py` и unit-тесты для scheduler, supervisor, worker event callbacks и telemetry callbacks.

### 2026-03-23 19:35:00
- Для `dvt_mcp.run_pytest` добавлен быстрый Docker preflight через `docker ps`, чтобы tool возвращал структурированную ошибку до запуска dockerized test runner, если Docker недоступен.
- В `services/dvt_mcp/operations.py` добавлена нормализация `timeout_sec`, чтобы `run_pytest` корректно обрабатывал строковый таймаут из MCP tool-call и не падал на сравнении/передаче таймаута.
- В `.codex/config.toml` для `dvt_mcp` поднят `tool_timeout_sec` до 900 секунд; обновлен блок `dvt_mcp` в `AGENTS.md` и добавлены unit-тесты `tests/unit/services/dvt_mcp/test_operations.py`.

### 2026-03-23 18:57:24
- Реализованы lifecycle и инфраструктура для `HARD_STOP`/`OOM_GUARD`: `CANCEL_REQUESTED`, `termination_reason`, telemetry процесса выполнения, execution registry, reconciler и supervisor в orchestrator.
- Исправлен `dvt_mcp.run_pytest` (fast Docker preflight, нормализация `timeout_sec`, увеличен `tool_timeout_sec`) и прогнан связанный набор unit-тестов: `23 passed`.
- В `tmp/task-worker-orchestrator-session-implementation.md` добавлен отчет с перечнем изменений текущей сессии.

### 2026-03-24 15:05:00
- Расширен `/system/services-stats`: для `task_workers` добавлены информативные поля `has_running_task`, `running_task_ram_used` и `running_task_ram_used_percent` на основе join `worker_registry` и `execution_registry`.
- Обновлены orchestrator servicer, client и HTTP-схемы Gateway, добавлен unit test `test_orchestrator_servicer.py`; связанный набор тестов прошел: `21 passed`.
- Автоматический `restart_service(gateway)` не выполнен, потому что сервис сейчас не запущен ни через plugin, ни через Docker (`effective_status=unknown`).

### 2026-03-25 14:27:56
- Добавлен общий orchestrator-side terminal finalizer для `SUCCESS`/`ERROR`/`CANCELLED`: обновление БД, cleanup execution registry и отправка `TaskExecutionStatusEvent` в websocket теперь выполняются единообразно.
- `worker_event_callbacks` и `execution_supervisor` переведены на новый helper, благодаря чему после `HARD_STOP` и `OOM_GUARD` UI получает финальный websocket event.
- Добавлены и обновлены unit-тесты (`test_task_finalizer.py`, `test_execution_supervisor.py`, `test_worker_event_callbacks.py`); связанный набор прошел: `25 passed`.

### 2026-03-26 13:19:00
- Добавлены пользовательские настройки OOM Guard в `AppConfig` с typed JSON-моделью `OOMGuardSettings` и `AppConfigProvider` с TTL-кешем для orchestrator.
- `TaskExecutionTelemetryEvent` и execution registry расширены полем `memory_limit_bytes`; task worker теперь репортит effective memory limit c учетом cgroup/container окружения.
- `TaskExecutionSupervisor` переведен на режимы `HOST_PRESSURE` и `WORKER_THRESHOLD`, читает policy через provider и использует специализированный `get_tasks_for_reconciliation(...)`.
- Восстановлен единый terminal finalization path через `task_finalizer` для worker terminal events; обновлены unit-тесты для AppConfig, provider, supervisor, finalizer и telemetry.

### 2026-03-23 13:57:35
- Добавлен CRUD-модуль `src/crud/db_connection` с функциями создания, чтения, обновления и мягкого удаления `DBConnection`.
- Добавлены исключения `DBConnectionNotFoundException` и `DBConnectionAlreadyExistsException`, а также категория `CRUD_DB_CONNECTION` в реестр исключений.
- Добавлены unit-тесты `tests/unit/src/crud/db_connection/test_crud.py` на создание, фильтрацию удалённых записей, обновление и soft delete.

### 2026-03-23 14:38:24
- Реализован эндпоинт `services/gateway/routes/utils/csv.py:get_columns` с эффективным извлечением заголовков CSV через `fsspec` и чтением только первой строки без полной загрузки файла.
- Добавлена поддержка путей к одному файлу, glob-паттернов и директорий как батча CSV-файлов с выбором первого CSV в детерминированном порядке.
- Добавлены unit-тесты на чтение заголовка, обработку escaped-разделителя и поведение для директории без CSV-файлов.

### 2026-03-24 12:34:38
- Добавлена новая модель `ProjectSchedule` с CRUD-слоем, миграцией `0039` и переносом источника истины для расписаний проектов с `Project.crontab` на отдельную таблицу `project_schedules`.
- Переведены `src/managers/project_scheduler.py`, `services/project_scheduler` и `services/gateway/routes/project/schedule.py` на работу с новой сущностью, добавлены soft-disable для `unschedule` и фильтрация списка расписаний по организации для `admin`.
- Обновлены internal-схемы и клиент scheduler, добавлены unit-тесты gateway scheduler routes и обновлены integration-тесты `services/project_scheduler`.

### 2026-03-24 15:17:31
- Обновлен `services/proxy`: добавлен стартовый скрипт генерации `Caddyfile` из `DVT_PUBLIC_URL`, включена автоматическая подготовка HTTP/HTTPS-адресов для Caddy и валидация конфига перед запуском.
- Обновлены `docker-compose.yaml`, `docker/docker-compose.dev.yaml` и `docker/docker-compose.ycm.yaml`: в `proxy` прокинут `DVT_PUBLIC_URL`, опубликован порт `443` наряду с `80`.
- Обновлен `install.sh`: добавлены подсказки, что `DVT_PUBLIC_URL` теперь используется и для proxy/Caddy, а `https://` требует DNS и открытых портов `80/443`.

### 2026-03-24 16:03:59
- Исправлены unit-тесты `tests/unit/src/crud/admin/user/test_create.py`.
- Моки перенаправлены на `get_users_by`, который реально вызывается внутри `create_user`, и удален лишний импорт `read_module`.

### 2026-03-25 11:55:39
- Добавлена миграция `0041_normalize_task_source_values.py`, которая нормализует значения `tasks.source` к верхнему регистру и добавляет check constraint `task_source` с допустимыми значениями `UI`, `API`, `SCHEDULER`.
- Обновлена модель `src/models/task.py`: для enum `Task.source` включено создание ограничения через `create_constraint=True`.
- Добавлены тесты на нормализацию legacy-значений `task source` и на ORM round-trip для `Task.source`.

### 2026-03-25 12:37:09
- Актуализирован `AGENTS.md` под текущее состояние репозитория.
- Исправлены названия и список сервисов (`project_scheduler`, `dvt_mcp`, `task_benchmarking`, `pycharm_plugin`), структура `src/`, `scripts/` и `tests`.
- Обновлены инструкции по окружению и командам запуска: вместо шаблона `{venv_dir_path}` указан `.venv3.13`, поправлены реальные entrypoint-модули в `scripts/services`, а compose-файлы перенесены в описание каталога `docker/`.

### 2026-03-25 12:43:43
- Уточнен раздел `Environment Setup` в `AGENTS.md`: убрана жесткая привязка к директории `.venv3.13`.
- Инструкции по запуску Python и сервисов переведены на шаблонный путь `<venv_dir>` с приоритетом `DVT_VENV_PATH`, чтобы документ был переносим между окружениями разработчиков.

### 2026-03-25 12:47:25
- В `AGENTS.md` добавлен блок с эксплуатационным контекстом проекта.
- Зафиксировано, что PROD для DVT — это клиентский инстанс на инфраструктуре заказчика, обычно один клиент соответствует одному инстансу.
- Добавлен архитектурный принцип: при прочих равных следует предпочитать меньшее количество сервисов и Docker-контейнеров, чтобы уменьшать эксплуатационную сложность на стороне клиента.

### 2026-03-25 14:01:08
- Переведены AI-джобы GitLab CI с Codex на Aider через OpenRouter.
- Добавлены `scripts/.ci/run_aider.py`, `scripts/.ci/prepare_release_diff.py`, `scripts/.ci/collect_failure_context.py` и probe-скрипт для Python-диагностики в Docker-контейнерах.
- Добавлены Aider-конфиги в `.ci/aider`, обновлены `write_changelog_b24` и `.b24_notify_stage` в `.gitlab-ci.yml`, удалены старые Codex-конфиги и runner.
- Для changelog настроен stable-to-stable diff без `rc`, для failure analysis настроен read-only анализ diagnostics bundle без правки исходного кода.
- Добавлены unit-тесты для подготовки релизного diff и вспомогательных функций Aider runner.

### 2026-03-25 14:07:50
- В `.gitlab-ci.yml` добавлены два ручных тестовых stage/job для проверки AI-обвязки через Aider на любой ветке: `manual_test_changelog_b24` и `manual_test_failure_analysis_b24`.
- Для changelog-теста добавлен helper `scripts/.ci/prepare_branch_changelog_diff.py`, который строит diff между `HEAD` и последним стабильным релизом без `rc`, а также отдельный Aider-конфиг `.ci/aider/write_changelog_branch_test.toml`.
- Добавлены отдельные B24-шаблоны с явной пометкой `TEST` для changelog и failure analysis, чтобы тестовые уведомления не смешивались с боевыми.
- Добавлен unit-тест `tests/unit/scripts/test_prepare_branch_changelog_diff.py` для проверки branch-to-stable diff.

### 2026-03-25 14:28:51
- Исправлен запуск Aider в CI для read-only репозитория: `scripts/.ci/run_aider.py` теперь монтирует весь репозиторий в контейнер `ro`, но подключает `.git` отдельным `rw` bind mount, чтобы Aider мог безопасно обновлять git config без доступа на запись к исходным файлам.
- В `.ci/aider/model_settings.yml` отключен `use_repo_map`, чтобы убрать лишние попытки построения и кэширования repo map в read-only окружении.
- Добавлен unit-тест на mount-логику `docker_volume_args` в `tests/unit/scripts/test_run_aider.py`.

### 2026-03-25 14:36:03
- Для CI-запуска Aider в `scripts/.ci/run_aider.py` принудительно отключен repo map через CLI-флаги `--map-tokens 0`, `--map-refresh manual` и `--no-auto-commits`, чтобы предотвратить сканирование всего монорепозитория и превышение контекстного лимита OpenRouter.
- В `tests/unit/scripts/test_run_aider.py` добавлен unit-тест, проверяющий наличие флагов отключения repo map в runner-скрипте.

### 2026-03-25 16:04:55
- Выполнен полный перевод AI-джобов GitLab CI с Aider на OpenCode.
- Добавлен новый runner `scripts/.ci/run_opencode.py` с runner-scoped установкой OpenCode в `/home/gitlab-runner/.local/share/opencode/<version>/`, pinned version и блокировкой одновременной установки.
- Для changelog добавлен compact seed bundle через `scripts/.ci/prepare_changelog_context.py` и точечные git-запросы через `scripts/.ci/changelog_query.py`, чтобы отказаться от передачи полного diff в модель.
- Для failure analysis добавлен compact seed bundle через `scripts/.ci/prepare_failure_analysis_context.py` и контролируемые docker/python-запросы через `scripts/.ci/failure_analysis_query.py`.
- Добавлены OpenCode-конфиги и agent-профили в `.ci/opencode`, обновлена `.gitlab-ci.yml`, удалены старые Aider-конфиги и runner, обновлён тестовый B24 шаблон.
- Добавлены unit-тесты `tests/unit/scripts/test_run_opencode.py` и `tests/unit/scripts/test_prepare_changelog_context.py`.
- Подготовлен отчёт о выборе `OpenCode` вместо `Goose` в `tmp/opencode-vs-goose-migration-report.md`.

### 2026-03-25 16:15:27
- Исправлена установка `OpenCode` в `scripts/.ci/run_opencode.py`: вместо внешнего install-скрипта добавлена детерминированная установка pinned-релиза через GitHub Releases API с выбором platform-specific asset, скачиванием и распаковкой binary в runner-scoped каталог `/home/gitlab-runner/.local/share/opencode/<version>/bin`.
- Обновлены unit-тесты для `run_opencode.py`: добавлена проверка выбора release asset для Linux x64 и сценария ошибки при отсутствии подходящего asset.

### 2026-03-25 16:20:53
- Исправлен Python-баг в `scripts/.ci/run_opencode.py`: в runtime-конфиге `OpenCode` заменен JSON-литерал `false` на корректный Python `False`, из-за чего `manual_test_changelog_b24` падал до запуска агента.
- Добавлен unit-тест на генерацию валидного JSON-конфига `OpenCode`, чтобы такие ошибки сериализации больше не проходили в CI.

### 2026-03-25 16:29:47
- Исправлен вызов `opencode run` в `scripts/.ci/run_opencode.py`: многострочный prompt больше не передается positional-аргументом CLI, а отправляется через `stdin`, как ожидает headless-режим `OpenCode`.
- Это устраняет падение `manual_test_changelog_b24`, где CLI ошибочно трактовал текст prompt как путь файла для `--file`.

### 2026-03-25 16:36:14
- В `scripts/.ci/run_opencode.py` добавлена генерация OpenRouter provider routing preferences для `OpenCode`: по умолчанию включен `require_parameters=true`, чтобы маршрутизатор OpenRouter выбирал только endpoints, поддерживающие tool use и другие параметры запроса.
- В `.gitlab-ci.yml` добавлены переменные `OPENCODE_OPENROUTER_REQUIRE_PARAMETERS` и `OPENCODE_OPENROUTER_ALLOW_FALLBACKS`, чтобы routing можно было настраивать через GitLab CI/CD Variables без правки кода.
- Обновлен unit-тест генерации runtime-конфига `OpenCode` с проверкой OpenRouter routing options.

### 2026-03-25 17:06:04
- Исправлен CI-раннер `OpenCode`: парсер итогового ответа теперь извлекает финальный текст из JSON events формата `type=text`/`part.text`, из-за чего `manual_test_changelog_b24` больше не должен падать с сообщением о пустом ответе.
- Уточнен prompt для `write_changelog.toml`: команда `changelog_query.py diff-file` теперь передается с явными `--from-ref` и `--to-ref`, чтобы агент не делал ошибочный первый вызов без обязательных аргументов.
- Добавлен unit-тест на разбор финального ответа из `OpenCode` text events.

### 2026-03-25 18:37:37
- Обновлен CI-контур `OpenCode`: для changelog и failure-analysis добавено сохранение полного raw ответа модели в `.jsonl` через `jsonl_output_path`, а в `.gitlab-ci.yml` настроены артефакты `tmp/ci-changelog*/opencode-output.jsonl` и `tmp/ci-failure-reports/*-opencode.jsonl`.
- Исправлен post-processing ответа `OpenCode` в `scripts/.ci/run_opencode.py`: при `output_mode=bbcode_sections` из финального текста отбрасывается вводная сводка перед первым разделом changelog/отчета, чтобы в итоговые файлы попадал только полезный BB-код.
- Расширена подготовка changelog-контекста: `scripts/.ci/prepare_changelog_context.py` теперь пишет seed-файлы по `services/ui` submodule (`ui_metadata.txt`, `ui_git_log.txt`, `ui_git_stat.txt`, `ui_git_name_status.txt`, `ui_changed_dirs.txt`), а `scripts/.ci/changelog_query.py` получил команды `ui-diff-file` и `ui-show-commit` и alias `--ref` для `show-commit`.
- Обновлены prompt и agent-инструкции для changelog, чтобы учитывать изменения UI и возвращать только чистый changelog без префикса.
- В runtime-конфиг `OpenCode` добавлены параметры reasoning (`reasoningEffort`, `reasoningSummary`, `include`), однако локальный smoke-test на `openrouter/deepseek/deepseek-v3.2` по-прежнему показывает `tokens.reasoning=0`, то есть текущая связка модели и провайдера не отдает reasoning наружу даже при включенной настройке.

### 2026-03-25 18:56:19
- Обновлены prompt и agent-инструкции для генерации changelog: теперь агент обязан формировать два крупных блока — `[B]👥 Для клиентов DVT[/B]` и `[B]🛠️ Для разработчиков DVT[/B]`.
- Для клиентского блока зафиксированы product-facing правила: акцент на бизнес-пользе, видимых изменениях в UI и сценариях, без ссылок на функции, классы, модули, миграции и другие внутренние сущности.
- Для developer-блока добавлены отдельные tech-facing секции (`Архитектура`, `API / Контракты`, `Extensions / SDK`, `Производительность`, `Тестирование`, `Рефакторинг`, `Fixes (technical)`, `DevOps / Infra`, `Зависимости`) и разрешение на использование технических терминов и внутренних имен.
- Оставлено правило, что секции внутри обоих блоков опциональны и не должны заполняться искусственно.

### 2026-03-25 19:17:39
- Исправлены unit-тесты CI-скриптов в `tests/unit/scripts`: тесты для `prepare_release_diff.py`, `prepare_branch_changelog_diff.py` и `prepare_changelog_context.py` теперь корректно пропускаются, если в окружении отсутствует исполняемый `git`.
- Это устраняет падение `scripts/docker/unit_tests.py` в tester-контейнере, где git не установлен, не затрагивая поведение самих CI-скриптов в реальном GitLab runner окружении.
- Локально проверен прогон затронутых тестов: `test_prepare_release_diff.py`, `test_prepare_branch_changelog_diff.py`, `test_prepare_changelog_context.py` проходят успешно при наличии git.

### 2026-03-26 17:29:39
- В `trash/scripts` тестовые скрипты запуска дополнительных `task_worker` переведены с локального старта Python-процессов на тот же механизм, что используется в CI/CD и dev-deploy: `docker compose --scale task-worker=N`.
- Helper `task_worker_launcher.py` теперь поднимает `task-worker` через `docker-compose.base.yaml` + `docker-compose.dev.yaml` и при необходимости создает сеть `dvt-net`, а скрипты `run_task_worker_2.py`, `run_task_worker_3.py`, `run_task_worker_4.py` выставляют общее количество контейнеров воркера в 2, 3 и 4 соответственно.

### 2026-03-26 17:32:04
- Для локального запуска нескольких `task_worker` на одном Windows-хосте обновлен `services/task_worker/helpers/worker_id.py`: `worker_id` теперь может автоматически включать `TASK_WORKER_INSTANCE_ID`, сохраняя старый fallback на `hostname`.
- В `trash/scripts` возвращены локальные Python-launcher-скрипты `run_task_worker_2.py`, `run_task_worker_3.py`, `run_task_worker_4.py`: они генерируют уникальный `TASK_WORKER_INSTANCE_ID` на процесс и запускают штатный `services.task_worker.main.run()` без Docker.
- Добавлен unit-тест `tests/unit/services/task_worker/helpers/test_worker_id.py` на env-based и hostname fallback поведение `worker_id`.

### 2026-03-26 18:28:52
- Усилена отказоустойчивость `execution_supervisor`: цикл теперь не падает целиком при ошибке шага, каждый шаг (`reap_stale`, `reconcile`, `apply_oom_guard`) выполняется изолированно с `logger.exception`, добавлены логи старта/остановки, деградации и восстановления итераций.
- `AppConfigProvider` сделан устойчивым к битым конфигам: при ошибке чтения/валидации `oom_guard_settings` используется fallback (последний валидный кеш или безопасный `DISABLED`), добавлено диагностическое логирование причин и выбранного fallback.
- Добавлены unit-тесты на аварийные сценарии: fallback провайдера при невалидном конфиге/ошибке БД и продолжение supervisor-итерации при падении одного шага.

### 2026-03-27 14:17:33
- Добавлен параметр `options` в `src/crud/project/read.py:get_projects_by(...)` для передачи ORM-опций загрузки.
- В `services/gateway/deps/project.py` добавлена предзагрузка `Project.user` через `selectinload`, чтобы избежать ленивой async-загрузки и ошибки `MissingGreenlet` при чтении проекта.

### 2026-03-30 12:48:06
- Переименован системный вход нод `variables` в `input_variables` и добавлен системный выход `output_variables` в `BaseNode`.
- Обновлена обработка переменных в пайплайне: поддержан формат `Dict[str, IO.VARIABLE]`, автоматическое заполнение `output_variables` и прием карт переменных из связанных выходов.
- Добавлена миграция `0043` для переезда ключа `graph_nodes.input_values` и handle `graph_edges` на новые имена, а также unit-тесты для миграции и затронутого runtime-поведения.

### 2026-03-30 12:50:19
- Удалена legacy-совместимость с именем `variables` в node-layer: убран alias из `BaseNode`, fallback в runtime-merge и legacy-переменная из `ExecutePython`.
- Актуализированы комментарии и повторно проверены unit-тесты для DSL, pipeline runtime, `ExecutePython` и миграции `0043`.

### 2026-03-30 14:01:18
- Восстановлена нода `CreateVariable` под текущий контракт переменных: возвращен `VariableOutput`, single-variable входы `name/type/value` и совместимое обновление `output_variables`.
- Добавлена новая нода `ManageVariables` для пакетного создания и переопределения переменных через текущий runtime-контракт `output_variables`.
- Добавлены unit-тесты на `CreateVariable` и `ManageVariables`, а также повторно проверены тесты runtime-резолва переменных в pipeline.

### 2026-03-30 14:24:15
- Удалена функциональная зависимость от `CreateVariable.variable`: нода `CreateVariable` больше не публикует отдельный output `variable` и работает только через `output_variables`.
- Обновлены runtime- и graph-тесты, переведены ссылки с `output-variable`/`output_name="variable"` на `output-output_variables`/`output_name="output_variables"`.
- Добавлена миграция `0044` для переименования legacy `graph_edges.source_handle` у старых графов `CreateVariable`.

### 2026-03-31 11:55:52
- Удалены legacy-схемы `NodeInput` и `NodeInputType` из `src/schemas/internal/node_data.py`, а `NodeData.inputs` переведены на строгую валидацию только канонических runtime-значений с `__dvt_type`.
- Упрощен парсинг входных значений в `src/types/input_values.py`, `src/utils/graph.py`, `src/crud/graph/common.py` и `services/task_benchmarking/utils.py`: удалена поддержка legacy-оберток `type/value`, fallback по `dvt_type` и автооборачивание raw/scalar значений.
- Обновлены unit/integration тесты и internal benchmark/example pipeline JSON в `services/task_benchmarking/pipelines/*` на канонический формат `__dvt_type`.
- В `tests/integration/fixtures/db_connections.py` добавлена подготовка MinIO bucket для стабильного S3 integration-прогона.

### 2026-03-31 12:15:44
- Схлопнута цепочка незакоммиченных миграций в одну ревизию `0043`: объединены переименование variable IO handles, переименование output handle у `CreateVariable`, добавление `show_variables_io` и data-migration для заполнения `var_type` у variable-input payload в `graph_nodes.input_values`.
- Удалены отдельные файлы миграций `0044` и `0045`, а unit-тесты миграций пересобраны под новый единый `tests/unit/migrations/versions/test_0043_rename_variables_io_to_input_output_variables.py`.
- В `src/types/input_values.py` в `NodeInputVariableValue` добавлено обязательное поле `var_type` с допустимыми значениями `user|system`; раздельная runtime-логика для `system` не добавлялась, поле пока используется как часть контракта.
- Обновлены backend unit-тесты и variable-payload в тестовых пайплайнах на новый формат `{"__dvt_type": "var", "var_type": "user", ...}`.

### 2026-03-31 13:53:43
- Добавлен статический контракт системных переменных нод через `NodeDefinition.system_variable_definitions`.
- В `BaseNode` добавлен helper `emit_system_variables`, а `VariableOutput` расширен полем `var_type` для явного разделения `user/system`.
- Добавлены unit-тесты на build-time валидацию схем системных переменных и runtime-эмиссию системных переменных в `output_variables`.

### 2026-03-30 15:15:00
- Для project scheduler добавлены отдельные update/delete маршруты расписаний проектов.
- В `ProjectSchedulerManager` реализованы методы обновления существующего расписания и полного удаления расписания из APScheduler и БД.
- Добавлен CRUD `delete_project_schedule` и обновлены интеграционные тесты роутов scheduler.

### 2026-03-30 15:19:58
- Для расписаний проектов в project scheduler update-маршрут переведен на `PATCH /projects/schedule/{project_id}` с отдельным partial-контрактом `ProjectSchedulePatchRequest`.
- В `ProjectSchedulerManager` обновление переработано в частичный patch: неподанные поля сохраняются, а `disabled` теперь можно изменять через patch с синхронизацией APScheduler и БД.
- Внутренний `SchedulerClient` дополнен методом patch для расписаний, интеграционные тесты обновлены и покрывают изменение `disabled` через patch.

### 2026-03-30 15:25:40
- В gateway для расписаний проектов добавлены внешние маршруты `PATCH /projects/scheduler/schedule/{project_id}` и `DELETE /projects/scheduler/schedule/{project_id}` с проверкой доступа к проекту.
- Gateway теперь проксирует patch/delete расписаний в scheduler service через `SchedulerClient`, а `scheduled_by_user_id` при patch подставляется из текущего пользователя.
- Обновлены unit-тесты gateway-роутов расписаний проектов для сценариев patch/delete и проверок доступа.

### 2026-03-30 17:18:56
- В `src/utils/cleanup.py` изменена очистка старых логов: записи с уровнем `ERROR` больше не удаляются, остальные по-прежнему очищаются по `created_at`.
- Добавлены unit-тесты на непакетную и пакетную очистку с исключением `ERROR`, а также на безопасный пропуск очистки при отсутствии колонки `level`.

### 2026-03-31 16:23:01
- Добавлена миграция `0043_add_node_task_source.py` для расширения `tasks.source` значением `NODE`.
- В downgrade добавлена защита: откат запрещается, если в таблице уже есть строки с `source = 'NODE'`.

### 2026-03-31 16:38:15
- Модель `Task.source` переведена с SQLAlchemy Enum на свободную строку `String` без жесткого ограничения значений в БД.
- Миграция `0043` переписана: в `upgrade` снимается `CHECK`-constraint `task_source` и расширяется тип колонки `tasks.source`, в `downgrade` добавлена проверка на произвольные значения перед возвратом старого ограничения.
- Добавлены и обновлены unit-тесты для новой string-семантики модели и миграции.

### 2026-04-01 17:29:19
- В `AGENTS.md` уточнены правила для `dvt_mcp.run_pytest`: `test_path` должен передаваться относительно каталога `tests/<type>`, без префикса `tests/unit`, а `arguments` нужно передавать списком строк, а не одной строкой.

### 2026-03-31 14:15:59
- Исправлена обработка linked `output_variables` в пайплайне: пустой mapping переменных больше не считается ошибкой и интерпретируется как валидный пустой источник.
- Добавлены регрессионные unit-тесты для `build_node_kwargs` и `PipelineProcessor` на сценарии с пустыми `output_variables` и смешанными multi-link источниками переменных.

### 2026-03-31 16:35:20
- Добавлена backend-поддержка вычисляемых переменных в `NodeInputVariableValue` через explicit `mode=name|expr` и sandboxed Jinja2 evaluator с native-результатом для типов `STRING/BOOLEAN/INT/FLOAT/DATETIME`.
- Расширены `InputField` и `InputDefinitionModel` метаданными `expression_enabled/expression_mode/expression_policy`, обновлены `ExecuteSQL` и `ExecutePython`, для Python-кода добавлен read-only объект `input_variables`.
- Добавлена миграция `0044_add_node_input_variable_mode.py`, unit-тесты на expression runtime и документ с ТЗ для UI в `tmp/ТЗ_по_UI_для_вычисляемых_переменных.md`.

### 2026-03-31 17:37:50
- Выделена отдельная модель `NodeInputExpressionValue` и обновлен backend-контракт input values: выражения больше не живут внутри `NodeInputVariableValue`.
- `VariableOutput`, типы и helper-ы работы с переменными вынесены в общий модуль `src/types/variables.py`, а системные переменные и тесты переведены на новый импорт.
- Ноды `CreateVariable` и `ManageVariables` получили поддержку direct variable/expression payload-ов, при этом обе создают только пользовательские переменные.
- Переписана миграция `0044` для нормализации старого формата `var + mode` в новый `expr`, обновлены unit-тесты и русскоязычное ТЗ для UI в `tmp/`.

### 2026-03-31 18:27:08
- Логика миграции `0044` перенесена в объединенную ревизию `0043`, отдельный файл `migrations/versions/0044_add_node_input_variable_mode.py` удален.
- Миграция `0043` переименована в `0043_normalize_variable_io_and_input_payloads.py` и теперь покрывает rename variable IO handles, `show_variables_io`, `var_type` и нормализацию payload-ов `var/expr`.
- Unit-тесты миграций пересобраны под новый файл `tests/unit/migrations/versions/test_0043_normalize_variable_io_and_input_payloads.py`, отдельный тест `0044` удален.

### 2026-03-31 19:35:55
- Упрощен backend-контракт вычисляемых выражений: удален `expression_mode`, `InputField.expression_enabled` заменен на `allow_expressions` со значением по умолчанию `True`.
- `InputField.expression_policy` теперь принимает объект `ExpressionPolicy` или литерал `"default"`, а в `NodeDefinition` сериализуется по имени политики.
- Обновлены runtime-resolve, unit-тесты и ТЗ `tmp/ТЗ_по_UI_для_вычисляемых_переменных.md` с учетом текущих компонентов в `dvt_ui` и задач для `ReadQueryFromDBV3`, `CreateVariable`, `ManageVariables`.

### 2026-04-01 17:23:13
- Упрощен backend-контракт input values: из `src/types/input_values.py` удален `NodeInputVariableValue`, ссылки на переменные теперь задаются через `NodeInputExpressionValue` c `expression_kind="single"`.
- В `src/utils/input_expressions.py` добавлена поддержка bare identifier для safe-имен переменных и явного fallback через `input_variables["..."]`, а ошибки отсутствующих переменных нормализованы до `ValueError`.
- Обновлена миграция `migrations/versions/0043_normalize_variable_io_and_input_payloads.py`: legacy payload `__dvt_type="var"` переводится в `expr`, а downgrade умеет восстанавливать прямые ссылки и expression-формулы.
- Переписаны целевые unit-тесты и обновлено русскоязычное ТЗ для UI в `tmp/ТЗ_по_UI_для_вычисляемых_переменных.md` под новый контракт без persisted-режима `var`.

### 2026-04-01 19:21:01
- Добавлен pre-push хук `check-migration-revisions` в `.pre-commit-config.yaml` для проверки уникальности `revision` в `migrations/versions`.
- Добавлен скрипт `scripts/.pre_commit/check_migration_revisions.py` и unit-тесты для сценариев без дубликатов и с конфликтующей ревизией.

### 2026-04-02 10:21:58
- Обновлен `README.md` под текущую архитектуру репозитория. Убраны устаревшие упоминания `store` и Kafka/Redpanda как основного execution flow, добавлены актуальные сервисы, поток выполнения через Gateway → Orchestrator → Celery/Valkey → Task Worker, обновлены команды локального запуска, Docker-compose и раздел troubleshooting.

### 2026-04-02 11:27:17
- Исправлены падения unit-тестов после обновления контрактов переменных и expression-inputs.
- Сделано `license_type` необязательным в `TaskInternal`, добавлен coercion `TIMEDELTA` для результатов expression-входов и восстановлена ошибка на дублирующиеся имена linked `input_variables`.
- Для `GetExistDBConnection` метаданные теперь читаются из уже установленного `connection`, а в orchestrator нормализована проверка online-статуса воркера.
- Обновлен unit-тест миграции на актуальный файл `0045_normalize_variable_io_and_input_payloads.py`.
- Пересобраны Python/gRPC-контракты `contracts/src/orchestrator/v1/orchestrator_pb2.py` и `contracts/src/ws_forward/v1/forward_pb2.py` без `mypy_out` из-за конфликта версий `mypy_protobuf` и runtime `protobuf` в локальном окружении.

### 2026-04-02 11:54:00
- В `src/pipeline/graph_utils.py` убрана проверка на дублирующиеся имена linked `input_variables`: при коллизии снова используется последнее пришедшее значение.
- Обновлен unit-тест `tests/unit/src/pipeline/test_graph_utils.py` под новое поведение без ошибки для пользователя.
- Проверены затронутые тесты пайплайна: `tests/unit/src/pipeline/test_graph_utils.py` и `tests/unit/src/pipeline/test_processor.py`.

### 2026-04-02 13:21:39
- Реализована загрузка метаданных SQLite в `core/metadata/db_metadata.py` через `sqlalchemy.inspect`, включая таблицы, представления, временные объекты, первичные ключи и индексы.
- Обновлен unit-тест `tests/unit/core/metadata/test_db_metadata.py`: вместо ожидания `NotImplementedError` теперь проверяется успешная загрузка SQLite-метаданных.

### 2026-04-02 13:27:33
- Исправлен unit-тест `tests/unit/src/nodes/connection/get_exist_db_connection/test_metadata.py`: мок `get_metadata` перенаправлен на модуль `get_exist_db_connection`, так как `infer_metadata()` использует локальный импорт функции.
- Повторный полный прогон unit-тестов завершился успешно.

### 2026-04-02 14:52:32
- В `src/pipeline/graph_utils.py` изменена логика `topological_sort`: при переданных `start_nodes` функция больше не добавляет в результат ноды, не входящие в зависимости целевых узлов.
- Обновлены тесты `tests/unit/src/pipeline/test_graph_utils.py` и `tests/unit/src/pipeline/test_processor.py`, чтобы зафиксировать игнорирование неподключенных веток и нод при выполнении пайплайна.

### 2026-04-02 15:00:09
- Скорректирована логика `topological_sort` в `src/pipeline/graph_utils.py`: при переданных `start_nodes` сохраняются все узлы из связных компонент графа размером от двух нод, а исключаются только полностью изолированные одиночные ноды без связей.
- Обновлены регрессионные тесты `tests/unit/src/pipeline/test_graph_utils.py` и `tests/unit/src/pipeline/test_processor.py`, чтобы зафиксировать сохранение несвязанных веток и игнорирование только одиночных неподключенных нод.

### 2026-04-02 17:21:47
- Доработана нода `src/nodes/transform/df_select_variables.py`.
- Исправлен расчёт агрегаций для Dask: вместо неподдерживаемого `DataFrame.agg(...)` добаваны безопасные вызовы агрегирующих методов Series, включая обработку `first` и `last`.
- Добавлена нормализация конфигурации `selected_variables`, валидация отсутствующих колонок, вывод корректного типа `VariableOutput` и сохранение входных переменных в `output_variables`.
- Нода экспортирована через `src/nodes/transform/__init__.py`.
- Добавлены unit-тесты `tests/unit/src/nodes/transform/test_df_select_variables.py` на типизацию, `first/last`, сохранение входных переменных и валидацию конфигурации.

### 2026-04-06 16:30:28
- Исправлена нода `Expand JSON` в `src/nodes/json/flatten_dict.py`: при превышении `max_total_rows` больше не строится усеченное декартово произведение массивов.
- Теперь нода сохраняет массивы без размножения в одной строке и пишет явное предупреждение, что устраняет потерю комбинаций и ложные дубли на сложных JSON.
- Добавлен регрессионный тест `test_expand_json_preserves_arrays_when_cartesian_product_exceeds_limit`.

### 2026-04-07 15:33:15
- Исправлен `ProjectSchedulerManager.patch_project_schedule`: при изменении `cron` без явного `next_run_time` больше не переиспользуется старое время следующего запуска, `APScheduler` теперь пересчитывает его автоматически.
- Добавлен unit-тест на сценарий изменения `cron` с автопересчетом `next_run_time`.

### 2026-04-07 15:44:36
- Доработан `ProjectSchedulerManager.patch_project_schedule`: при изменении `cron` теперь игнорируется эхо-возврат старого `next_run_time` из клиента, если UI присылает его вместе с patch-запросом. Это позволяет пересчитывать следующее время запуска сразу после `PATCH`, без рестарта `project_scheduler`.
- Добавлен unit-тест на сценарий, где клиент отправляет новый `cron` и старый `next_run_time` в одном payload.

### 2026-04-03 12:29:04
- Выполнен рефактор `src/node_dsl/base_node/base.py`: логика работы с variable-портами, system variables, extension state и исполнением вынесена в отдельные миксины.
- Добавлены unit-тесты на нормализацию `input_variables`, обновление `output_variables` и резолвинг metadata расширений для `BaseNode`.

### 2026-04-03 14:35:39
- Переведен execution contract пайплайна с `outputs_to_execute` на `target_nodes` в схемах, процессоре, benchmarking-утилитах и интеграционных тестах.
- Упрощена `topological_sort`: при переданных `target_nodes` теперь возвращается только минимальный upstream-подграф без добавления посторонних связанных веток.
- Обновлен парсинг `execution_insights` в `services/dvt_mcp/operations.py` и документация `dvt_mcp` в `AGENTS.md` под новые логи и ключ `target_nodes`.
- Скорректированы unit-тесты пайплайна и добавлен кейс для `METADATA_ONLY`, подтверждающий subtree-only execution order.

### 2026-04-03 17:23:02
- В `core/db/read_v3` добавлена поддержка `ValueKind.JSON` для output-колонок и dtype `object` в SQL executor.
- Planner'ы `table/query` теперь распознают `JSON/JSONB`, разрешают их в выходных колонках и отдельно запрещают использование JSON-колонок как `partition_col` с явной ошибкой.
- Добавлены unit-тесты для JSON kind/object dtype и PostgreSQL integration-тесты для чтения `JSONB` и запрета JSON partition key.

### 2026-04-03 17:38:34
- Исправлена деградация `read_v3` для JSON-колонок на этапе сборки Dask DataFrame: отключена автоконверсия `object -> string` только для планов с `ValueKind.JSON`, чтобы `dict/list` сохранялись как Python-объекты.
- Добавлен unit-тест на сохранение `object` dtype и native JSON-значений в `frame_from_executor`.
- Повторно проверены unit-тесты `core/db/read_v3` и PostgreSQL integration-тесты для JSON output/partition key.

### 2026-04-03 18:01:37
- Добавлена инкрементальная metadata-оптимизация для `process_graph_op`: metadata-задача теперь ставится только при изменении `inputValues` ноды или при создании edge и получает `metadata_changed_node_ids` для расчета затронутого подграфа.
- Расширены `enqueue_task_from_project`, `graph_crud.get_graph_by` и `build_pipeline_from_graph` поддержкой union-режима для нескольких финальных нод через `final_node_ids`.
- В `PipelineProcessor` для `ExecMode.METADATA_ONLY` добавлен cache-frontier path: upstream-ноды вне downstream-closure от измененных нод могут восстанавливаться из metadata-cache до инстанцирования и исполнения.
- Добавлены unit-тесты на downstream target discovery, multi-target pipeline build, incremental metadata cache reuse и helper-логику `graph_operations`.

### 2026-04-03 19:06:40
- Обновлены integration-тесты `tests/integration/src/pipeline/test_processor.py` под новую семантику `target_nodes`.
- Удалена зависимость от фиктивной `display`-ноды, а проверки переведены на чтение dataframe-результатов из `PipelineProcessor.nodes_outputs[...]["output"]`.

### 2026-04-06 12:48:51
- Исправлена эмиссия системных переменных с пустыми значениями: `emit_system_variables` теперь сохраняет явно переданные `None`, а не удаляет их.
- Добавлены unit-тесты на два сценария: явный `None` публикуется как системная переменная, а необязательное поле без явной установки по-прежнему не эмитится.

### 2026-04-07 15:19:37
- Завершен переход запуска задач с `final_node_id`/`final_node_ids` на `target_nodes` в backend, Gateway и `dvt_mcp`.
- Добавлена нормализация `target_nodes`, обновлены тесты Gateway и graph utils без правок в `services/ui`.

### 2026-04-07 15:26:18
- Настроен pytest на запись служебных файлов в `tmp/pytest`: cache, basetemp, debug temp root, кастомный `tmp_path` и стандартный `tempfile`.
- Исправлен параметр pytest-конфигурации `testspaths` на `testpaths`.

### 2026-04-09 14:08:53
- Исправлен batch-delete проектов в gateway: при отсутствии доступных проектов роут теперь передает список запрошенных `project_ids` в `ProjectsNotFoundException`, чтобы ответ содержал проблемные ID.
- `ProjectsNotFoundException` переведен на `RegisteredHTTPException` с корректным HTTP 404 и текстом детали, что устраняет 500 в тесте `test_batch_delete_projects_returns_404_when_nothing_accessible`.

### 2026-04-09 14:23:31
- Исправлены admin user роуты gateway: в `services/gateway/routes/impl/admin/user.py` добавлена явная проверка admin-доступа внутри impl-слоя, чтобы unit-тесты с overridden dependency не обходили авторизацию.
- Запрещены self-delete и изменение собственной роли/организации через admin endpoint с корректным `403` (`UserForbiddenHTTPError`), при этом безопасное self-update без понижения привилегий остается доступным.
- В unit-тестах добавлена fixture `mock_regular_user` и исправлены невалидные payload'ы в `test_admin_access_denied_for_regular_user_on_all_endpoints`, чтобы тест проверял именно авторизацию, а не `422` от схемы.

### 2026-04-09 14:40:25
- Рефакторинг admin user gateway: проверки доступа и self-action ограничения вынесены из `services/gateway/routes/impl/admin/user.py` в отдельный policy-модуль `services/gateway/policies/admin_user.py`.
- Impl-слой admin user упрощен до orchestration: он вызывает policy-функции и CRUD, без локальных `_ensure_*` утилит. Поведение сохранено, unit-тесты `test_user_crud.py` проходят без изменений контракта.

### 2026-04-09 14:51:15
- Добавлена server-side валидация ИНН организации в gateway: создан policy-модуль `services/gateway/policies/organization.py`, который нормализует ИНН и отклоняет некорректные значения (нецифровые или длиной не 10/12) с HTTP 400.
- В `services/gateway/routes/impl/organization.py` create/update организации теперь используют policy-нормализацию ИНН, а в `services/gateway/exceptions/organization.py` добавлено `OrganizationInvalidINNHTTPError`.
- Исправлено падение теста `test_create_organization_with_invalid_inn`; весь `tests/unit/services/gateway/routes/public/organization/test_organization_crud.py` проходит.
### 2026-04-08 11:15:09
- Добавлен отчет `tmp/merlion_dvt_tz_gap_report.md` с анализом проекта `CDC Example` относительно ТЗ по выгрузке данных в S3/Parquet.
- В отчете описаны текущий backend-пайплайн, расхождения с требованиями, лишние demo-элементы и пошаговый план доведения решения до промышленного варианта.

### 2026-04-08 11:15:58
- Исправлен заголовок в файле `tmp/merlion_dvt_tz_gap_report.md` после проверки итогового Markdown-отчета.

### 2026-04-08 12:23:43
- Добавлен асинхронный путь получения метаданных нод через `resolve_metadata()` в Node DSL.
- Обновлен `PipelineProcessor`: метаданные теперь резолвятся асинхронно и больше не читаются напрямую через `node.metadata` в runtime-пути.
- Нода `GetExistDBConnection` переведена на асинхронное чтение внутренней DVT Postgres-базы при сохранении публичного выхода `sa.Engine`.
- Обновлены unit-тесты для нового контракта async metadata и поведения `GetExistDBConnection`.

### 2026-04-08 12:49:05
- Переписан отчет `tmp/merlion_dvt_tz_gap_report.md` по проекту `CDC Example`.
- Архитектурные рекомендации изменены так, чтобы не предлагать Merlion-специфичные сущности внутри DVT: без новых нод, сервисов и таблиц в системной БД DVT.
- В отчете предложен подход, при котором DVT остается универсальным orchestrator, а вся предметная конфигурация, состояние загрузок и аудит выносятся во внешний контур Merlion.

### 2026-04-08 14:16:48
- Подготовлен demo-комплект для Merlion в `tmp/merlion`: добавлены скрипты `ensure_orders_demo_tables.py` и `mutate_orders_demo_data.py`, создан новый graph export `graph-export-merlion-tz-orders-v2.json` и отчет `dvt_mcp_gap_report.md`.
- Переписан основной отчет `tmp/merlion_dvt_tz_gap_report.md` под новый контекст: demo-проект как шаблон для заказчика, переход на `orders`, generic улучшения DVT без Merlion-специфичных сущностей.
- Проверено создание `orders` и `stg_orders` в тестовом MSSQL и наполнение `orders` realistic demo-данными.

### 2026-04-08 15:11:05
- Выполнен рефактор доменных типов из `src/types`: `input_values` перенесены в пакет `src/node_dsl/input_values`, `variables` — в `src/node_dsl/variables`, alias `Pipeline` — в `src/pipeline/types`.
- Переведены импорты в исходном коде, схемах Gateway и тестах на новые доменные пакеты, удалены устаревшие модули `src/types/input_values.py`, `src/types/variables.py`, `src/types/pipeline.py` и `src/utils/variables.py`.
- Добавлены отдельные unit-тесты для helper-логики `input_values` и `variables`, а также облегчены `src/node_dsl/__init__.py` и `src/pipeline/__init__.py` через ленивые импорты.
- Исправлена инициализация registry в `src/node_dsl`, чтобы новые доменные подмодули не создавали циклические импорты и корректно работали вместе с тестовой ручной регистрацией нод.

### 2026-04-08 19:02:40
- Доменные helper-модули `src/utils/graph.py` и `src/utils/input_expressions.py` вынесены из shared-слоя.
- Добавлены пакеты `src/pipeline/graph` и `src/node_dsl/input_expressions`, обновлены импорты в `src`, `services` и тестах.
- Удалено дублирование `coerce_expression_result`, добавлены прямые unit-тесты для expression evaluation и разнесены тесты graph builder/targets.

### 2026-04-08 19:49:37
- Для demo-проекта Merlion реализован внешний metadata/config layer в `tmp/merlion` без изменений системной БД DVT.
- Добавлены скрипты `ensure_orders_demo_metadata_layer.py`, `reset_orders_demo_metadata_state.py`, `validate_orders_demo_metadata.py` и общий helper `demo_metadata_common.py`.
- Собран новый `graph-export-merlion-tz-orders-v3.json` с чтением внешнего SQL metadata layer, инкрементальным чтением по watermark и обработкой пустого источника через sentinel parquet.
- Проверены выполнение metadata-скриптов, генерация v3-графа и синтаксическая корректность новых Python-файлов.

### 2026-04-09 11:19:23
- Исправлена инициализация `src/node_dsl/input_expressions`: убран import-cycle, добавлена идемпотентная инициализация registry и публичные read-only accessor-функции для filters/tests/globals и default policy.
- В `Gateway` добавлен новый маршрут `GET /config/expressions` с HTTP-схемами ответа для UI-конфигурации expression environment.
- Добавлены и обновлены unit-тесты на чистый импорт пакета, idempotent registry init, expression config accessors и новый gateway route.

### 2026-04-09 13:37:26
- Добавлен отчет `tmp/illian/report.md` с анализом проблемы доступа к DVT по домену `https://dvt.illan.ru`.
- Описана корневая причина: несоответствие между логикой `install.sh` для HTTPS и фактической конфигурацией встроенного proxy.
- Перечислены варианты решения: внешний reverse proxy, исправление deployment bundle и временный обходной путь.

### 2026-04-09 18:19:05
- Добавлен новый metadata-путь выполнения нод через `process_metadata()` с поддержкой синхронной и асинхронной реализации.
- Для `BaseNode.process_metadata()` добавлен warning-фоллбек на `process()`, а metadata-ветки в базовых классах обновлены на использование нового контракта.
- Для `ReadQueryFromDBV3` и `ReadTableFromDBV3` реализован асинхронный `process_metadata()`, который формирует пустой типизированный `Dask DataFrame` по метаданным без запуска полного чтения.
- В `read_v3` добавлена MSSQL-нормализация embedded query через `sqlglot`: top-level `ORDER BY` в query mode теперь автоматически получает `OFFSET 0 ROWS` перед встраиванием во внутренний CTE/derived table.
- Добавлены unit-тесты на новый контракт `process_metadata`, на построение типизированного empty output и на MSSQL-нормализацию query; интеграционный MSSQL-тест дополнен сценарием с `ORDER BY` и проверкой типов метаданных.

### 2026-04-09 18:38:21
- Сделан статический публичный API для `src/node_dsl`: убран динамический `__getattr__`, добавлены явные package exports и типизированные обертки для registry-функций с автоинициализацией.
- Добавлен unit-тест на статические exports пакета `src.node_dsl` и вызов инициализации перед чтением registry.
- Разорван цикл импортов для статической загрузки `BaseNode`: `ProjectSettings` и `ProjectVariables` переведены на явные Pydantic-модели без import-time зависимости от `src.models`, а `ProjectSettingsNodeMixin` переведен с ORM `Project` на schema `ProjectSettings`.

### 2026-04-09 19:11:26
- Упрощен `src/node_dsl/__init__.py`: удалены локальные wrapper-функции для `get_node/get_all_nodes/get_definition/get_all_definitions/get_hooks/get_all_hooks/run_hooks/run_hooks_async`, пакет снова стал обычным статическим re-export.
- Добавлен общий bootstrap-helper для registry в `src/node_dsl/registry/_bootstrap.py`, а автоинициализация нод перенесена в модули `registry/nodes.py`, `registry/definitions.py` и `registry/hooks.py`.
- Обновлен `src/node_dsl/_init_nodes.py`, чтобы после полной регистрации помечать registry как bootstrapped, и добавлены тесты на прямые re-export'ы и bootstrap при чтении registry.

### 2026-04-10 14:58:47
- Добавлен новый Markdown-документ `tmp/ТЗ_по_backend_metadata_variables_expressions.md` с техническим заданием по backend-доработке поддержки переменных и выражений в режиме `METADATA_ONLY`.
- В ТЗ зафиксированы целевая архитектура, ограничения, phased-подход, требования к backend metadata-контракту без изменений `core.types.Metadata`, а также критерии приемки и тестовый план.
- UI и остальной код проекта в рамках этой задачи не изменялись.

### 2026-04-10 16:09:37
- Реализована backend-поддержка переменных и выражений в режиме `METADATA_ONLY`: добавлены `UnresolvedValue`, metadata `VARIABLE_MAP`, metadata-aware разрешение выражений и переменных, а также `process_metadata()` для `CreateVariable`, `ManageVariables` и `DataFrameSelectVariables`.
- Обновлены backend-схемы metadata и OpenAPI include-модели для нового типа `VARIABLE_MAP`, исправлен цикл импортов через облегчение `src.node_dsl.registry.__init__` и прямой импорт `node_typing` в schema/field-модулях.
- Добавлены и обновлены unit/regression тесты для variable metadata, metadata-flow пайплайна и package exports; удалено ошибочное backend-ТЗ из `tmp/` и добавлено UI-only ТЗ `tmp/ТЗ_UI_поддержка_VARIABLE_MAP_metadata.md`.

### 2026-04-10 18:27:27
- Обновлен якорь `postgres_backup_step` в `.gitlab-ci.yml`.
- Резервный дамп Postgres переведен в режим `best effort`: при отсутствии credentials, контейнера, запущенного состояния контейнера или ошибке `pg_dump` шаг теперь логирует `skip` и не роняет весь job.
- Добавлена очистка неполного dump-файла при ошибке `pg_dump`.

### 2026-04-13 16:56:15
- Вынесена общая логика извлечения metadata типов SQL-запросов в `core/db/read_v3/query_metadata.py` и подключена в `read_v3` planner.
- Роут `services/gateway/routes/utils/sql_query_to_metadata.py` переведен на переиспользование этой логики для MSSQL, что исправляет определение строковых типов при `pyodbc cursor.description` с Python class type codes.
- Добавлены unit-тесты на общий helper и на `_get_metadata` для MSSQL-сценария с `UNKNOWN` типами.

### 2026-04-13 17:55:56
- Устранена циклическая зависимость, из-за которой сервис `gateway` падал при импорте `services.gateway.migrate` в Docker.
- В `src/types/metadata.py` убрана зависимость от `src.node_dsl.constants` и использован строковый литерал для ключа `output_variables`.
- Добавлен регрессионный тест `tests/unit/services/gateway/test_migrate_import.py`, проверяющий успешный импорт модуля миграций без circular import.

### 2026-04-13 20:04:06
- Добавлена нода `CreateTableFromMetadata` в `src/nodes/tool` для создания таблицы БД по входным `DataFrameMetadata` с режимами `on_exists: ignore|recreate|error` и сигнальным выходом.
- Нода использует общие DDL-хелперы из `core.db.ddl`, поддерживает `table_create_spec`, учитывает `database_name/schema_name` и инвалидирует meta-cache подключения после создания или пересоздания таблицы.
- Обновлен экспорт `src/nodes/tool/__init__.py` и добавлены unit-тесты на создание таблицы, режимы `ignore/recreate`, применение `table_create_spec` и очистку meta-cache.

### 2026-04-14 16:13:04
- Добавлен metadata variable prepass для `METADATA_ONLY`: `PipelineProcessor` теперь заранее исполняет upstream-ноды, которые подготавливают переменные для metadata-зависимых DB-нод, и повторно не запускает уже подготовленные узлы.
- Для `OUTPUT_NODE` в metadata-only перенесен ранний skip до инстанцирования ноды.
- Обновлены `ReadQueryFromDBV3` и `ReadTableFromDBV3`: добавлен opt-in в prepass и soft-fallback на пустую схему при неразрешенных переменных вместо падения.
- В `ReadTableFromDBV3.process_metadata()` отключен emit системных переменных, если целевые значения остаются неразрешенными.
- Добавлены unit-тесты на prepass для DB read-нод, ранний skip output-нод и soft-unresolved поведение metadata inference.

### 2026-04-14 21:10:18
- Расширен контракт `core/db/write_v3`: добавлены политики `on_extra_df_columns` и `on_missing_df_columns` для управления расхождениями колонок между входным DataFrame и существующей таблицей.
- Реализовано общее выравнивание колонок для SQL и ClickHouse executor'ов с поддержкой игнора лишних колонок, пропуска отсутствующих nullable/default колонок, default-only insert и явной ошибки при отсутствии upsert-ключа.
- Обновлены README и unit-тесты для `write_v3`: покрыты сценарии ignore/error для extra/missing колонок, zero-common/default-only insert, defer-to-DB поведение и проброс новых параметров на уровне ноды.

### 2026-04-14 21:42:20
- В `DataFrameGroupByAgg` добавлена поддержка global aggregation: при пустом `group_by_columns` и заданных `new_cols/source_cols/agg_funcs` агрегации теперь применяются ко всему DataFrame и возвращают одну строку результата.
- Убрано прежнее silent no-op поведение для пустого `group_by_columns`: конфигурация без группировки и без агрегаций теперь валидируется как ошибка.
- Добавлены unit-тесты на глобальную агрегацию по всему DataFrame и на fail-fast валидацию пустой конфигурации без `group_by_columns` и агрегаций.

### 2026-04-15 11:09:02
- Добавлен проектный Stop-hook в `.codex/hooks.json` для запуска dockerized unit-тестов через `scripts/docker/unit_tests.py`.
- Добавлена обертка `.codex/hooks/run_unit_tests_stop.py` с безопасным пропуском на Windows и при недоступном Docker, а также с кэшем состояния и логированием результата.
- В `.gitignore` добавлены локальные файлы состояния и лога hook-а, чтобы они не попадали в git.

### 2026-04-15 14:25:22
- Обновлен dockerized integration runner: `scripts/docker/integration_tests.py` теперь перед запуском тестов пересобирает актуальные prod-образы `gateway`, `orchestrator`, `task-worker`, `project-scheduler` и использует локальный `DOCKER_CONFIG` в `tmp/docker-config`, чтобы избежать ложных падений на устаревших образах и конфликтов с `buildx` lock.
- В `scripts/docker/test_runner.py` добавлен helper `build_prod_compose_command`, а в `tests/unit/scripts/docker/test_test_runner.py` — unit-тест на состав команды для prod compose.

### 2026-04-15 15:26:47
- В `DataFrameFilter` добавлен контракт operand `type="expression"` для правого операнда условий с поддержкой canonical single-expression payload.
- Обновлен `filter_rules_spec` до версии 3, добавлен metadata-only путь без вычисления маски и расширены unit/pipeline тесты для expression-фильтров и сохранения поведения column-vs-column.

### 2026-04-15 16:47:23
- Исправлена сборка задач с `target_nodes`: явные целевые ноды теперь всегда оборачиваются в `ServiceOutputNode`, а в `TaskInternal.target_nodes` передаются synthetic service-output ids для фактической материализации результата.
- Добавлены unit-тесты для подмены execution targets и обертки явных output-нод.

### 2026-04-15 17:59:48
- Исправлена генерация SQL для `read_v3` custom grouping: подсчет значений теперь группируется через derived table, чтобы MSSQL не падал на `GROUP BY` по алиасу `v`.
- Добавлены unit-тест SQL-шаблона и MSSQL integration-тест для `ReadQueryFromDBV3` с `partition_grouping` mode `prefix`.

### 2026-04-16 12:12:13
- Добавлена backend-нода `ReadVariablesFromDB` с двумя режимами работы: ручное описание переменных через `Dict[str, VariableConfiguration]` и сырой SQL-запрос с проверкой на ровно одну строку результата.
- Для ручного режима реализованы агрегации `min`, `max`, `count`, `count_distinct`, `sum`, `avg`, `first`, `last`, валидация `order_by_column` для `first/last`, fail-fast политика для `NULL` и публикация schema/additional_schema для будущего UI.
- Добавлены unit-тесты на manual/sql сценарии, metadata-only выполнение, ошибки по `NULL` и схему поля `manual_variables`.

### 2026-04-16 14:32:54
- Добавлена поддержка `nullable` и literal-only `default` для переменных и выражений в `CreateVariable`, `ManageVariables` и `ReadVariablesFromDB`.
- Для DSL helper-ов добавлена корректная обработка `None` в expression/value coercion и общий policy-применитель для fallback/default.
- `ReadVariablesFromDB` расширена поддержкой `sql_variables`, обработкой `0 rows` в SQL-режиме через default/nullability и выводом типов переменных из схемы/метаданных, если итоговое значение осталось `None`.
- Обновлены unit-тесты для helper-ов, primitive variable nodes и `ReadVariablesFromDB`.

### 2026-04-17 12:01:15
- В узле `src/nodes/extract/read_variables_from_db.py` добавлена поддержка `target_dtype` для конфигураций переменных в режимах `manual` и `sql`.
- Реализовано приведение значений и `default` к целевому типу через DSL-хелперы переменных, а также исправлена обработка `NULL` без явно заданного `default`.
- Обновлены unit-тесты для сценариев переопределения типов, zero-row overrides, ошибок валидации и схем входных параметров.

### 2026-04-17 12:32:28
- Добавлен аналитический отчет `tmp/list_variable_support_analysis.md`.
- В отчете зафиксирован план локального рефактора типовой системы для переменных, устранения дублирующихся helper-ов и последующего введения признака `is_list_type` для поддержки list-переменных в `CreateVariable`, `ManageVariables` и `ReadVariablesFromDB`.

### 2026-04-17 13:46:51
- Дополнен отчет `tmp/list_variable_support_analysis.md`.
- Добавлен анализ фактического использования `IOMeta.__contains__` через AST-поиск по репозиторию, рекомендации по переводу `VariableType` на alias на основе значений `IO`, а также вывод о нецелесообразности и технической проблемности наследования `IO` от `DataType`.

### 2026-04-17 14:56:15
- Выполнен этап 1 рефактора типовой системы переменных.
- Добавлен единый scalar type layer `src/node_dsl/variable_type_system.py` и совместимый re-export в `src/node_dsl/variables/type_system.py`.
- На новый слой переведены variable helpers, expression coercion, system variables, `ReadVariablesFromDB`, `DataFrameSelectVariables` и `TypeResolver` без внедрения `is_list_type`.
- Удалена внутренняя зависимость `TypeResolver` от `IOMeta.__contains__`, добавлен helper `try_get_io_member`.
- Добавлены unit-тесты для нового type layer и для прямого/ForwardRef-resolve в `TypeResolver`; таргетный pytest-прогон по затронутым модулям прошел успешно.

### 2026-04-17 15:57:32
- Реализован второй этап рефактора переменных: добавлена поддержка list-переменных через флаг `is_list_type` в `CreateVariable`, `ManageVariables` и `ReadVariablesFromDB`.
- Унифицированы helper-функции для коэрции/инференса scalar и list значений, расширены метаданные переменных и обработка unresolved/default/nullable сценариев.
- В expression runtime добавлен immutable-тип для списков, чтобы выражения с list-переменными поддерживали операции вроде конкатенации без потери immutability.
- Добавлены и обновлены unit-тесты для variable helpers, metadata, primitive nodes, `ReadVariablesFromDB` и input expressions.

### 2026-04-20 15:27:59
- Добавлен новый CI-контур `write_merge_summary_b24`, который после merge в `dev` и `main` собирает compact context bundle по конкретному MR, запускает OpenCode-агента `merge-summary`, сохраняет артефакты в `tmp/ci-merge-summary` и отправляет отдельное B24-сообщение с business- и developer-summary.
- Добавлены скрипты `scripts/.ci/merge_request_api.py`, `prepare_merge_summary_context.py` и `merge_summary_query.py`, а также новые конфиги `.ci/opencode/write_merge_summary.toml`, `.ci/opencode/agents/merge-summary.md` и `.ci/b24_messages/merge_summary_message.toml`.
- Добавлены unit-тесты для подготовки merge-summary context и query helper; локально подтвержден успешный прогон затронутых тестов CI-скриптов.

### 2026-04-20 15:47:55
- Исправлен резолв merge request для CI-скриптов merge summary и merge notification.
- Добавлен fallback от прямого lookup по `!IID` к поиску MR по `CI_COMMIT_SHA` и по веткам merge-коммита, чтобы job `write_merge_summary_b24` не падал на merge-коммитах с недоступным `/projects/:id/merge_requests/:iid`.
- Добавлены unit-тесты на fallback-логику `merge_request_api`.

### 2026-04-20 16:01:06
- Доработан fallback резолва merge request в CI: `404` от GitLab endpoint `/repository/commits/:sha/merge_requests` больше не прерывает поиск и переводит логику к branch-based search.
- Обновлен job `write_merge_summary_b24`: при `skip` теперь создаются placeholder artifacts (`summary.txt`, `opencode-output.jsonl`, `context/skip_reason.txt`), чтобы GitLab не ругался на пустую загрузку artifacts.
- Добавлен unit-тест на сценарий commit lookup 404 с успешным fallback по веткам.

### 2026-04-20 16:14:32
- Переведен `write_merge_summary_b24` на git-first сбор контекста без зависимости от GitLab MR API.
- `prepare_merge_summary_context.py` теперь строит summary по текущему merge-коммиту и диапазону `HEAD^1..HEAD`, извлекает ветки, автора изменений и merge-коммит metadata из локального git и CI-переменных.
- Обновлены OpenCode prompt/agent и B24 template под merge-коммит вместо merge request.
- Добавлены и обновлены unit-тесты для git-first merge summary context.

### 2026-04-21 14:55:17
- В `DataFrameCastColumnType` добавлено приведение дробных значений к integer-типам через усечение дробной части по семантике Python `int()` перед `Int64`/`int*` cast.
- Добавлен unit-тест на каст дробных значений и `NaN` в `Int64`, подтверждающий поведение `1.9 -> 1`, `-1.9 -> -1`, `NaN -> <NA>`.

### 2026-04-21 15:00:31
- Исправлен `DataFrameCastColumnType` после регрессии с Dask tokenization: integer-cast больше не использует локальный `lambda` в `map_partitions`, а выполняется через module-level функцию с детерминированной токенизацией.
- Повторно подтверждены unit-тесты для datetime и усечения дробной части при integer-cast.

### 2026-04-21 15:02:31
- Устранена ошибка deterministic hashing в `DataFrameCastColumnType`: integer-cast переведен с функции на dataclass-callable с `__dask_tokenize__`, совместимый с Dask expression tokenization.
- Повторно подтверждены unit-тесты на datetime-каст и усечение дробной части при приведении к integer-типам.

### 2026-04-21 11:31:32
- В `dvt_mcp` добавлены инструменты для работы с DBConnection: создание/обновление, список, проверка подключения, выполнение SQL и создание тестовой таблицы.
- Обновлена документация `AGENTS.md` с описанием новых возможностей `dvt_mcp`.

### 2026-04-21 14:05:16
- Исправлена обработка SQLAlchemy URL для Oracle с параметром `service_name`: добавлен общий helper, предотвращающий добавление `database` в path URL.
- Обновлены актуальные места создания engine для `ReadTableFromDBV3`, `WriteDataFrameToDBV3`, DDL engine и `ReadVariablesFromDB`.
- Добавлены интеграционные Oracle-тесты для `ReadTableFromDBV3`, `WriteDataFrameToDBV3`, `CreateTable` и `ReadVariablesFromDB` с непустым `database_name` и URL через `service_name`.

### 2026-04-21 17:07:08
- Исправлена генерация SQL для Oracle в `read_v3` query mode: case-sensitive имена выходных колонок из пользовательских запросов теперь переиспользуются с точным экранированием, без изменения общего поведения quoting для таблиц и схем.
- Добавлены unit-тесты на Oracle result-column quoting и planner/executor path, а также integration-регрессия для `ReadQueryFromDBV3` с алиасами `"Source"` и `"Kontragent"`.

### 2026-04-21 17:14:19
- Доработан Oracle-фикс для `read_v3`: разделены display-имена колонок и точные SQL-имена из metadata, чтобы planner ссылался на `PERIOD`/`"Source"` по реальным Oracle identifiers, даже если pandas возвращает `period` в нижнем регистре.
- Добавлен integration-регрессионный тест для Oracle на смешанный сценарий с `PERIOD`, `"Source"` и `partition_col="period"`.

### 2026-04-21 17:34:11
- Обновлен `read_v3` для query mode: публичные имена колонок и metadata теперь сохраняют exact-case из результата запроса, а не нормализуются по регистру.
- Добавлены unit- и integration-тесты на mixed-case aliases для `ReadQueryFromDBV3`, обновлены oracle-специфичные проверки exact-case вывода.
- В `write_v3` добавлена явная ошибка для case-only mismatch между колонками DataFrame и целевой таблицы без авто-переименования, с отдельными unit-тестами на append/upsert сценарии.

### 2026-04-21 17:47:46
- Исправлен executor-layer `read_v3` для query mode: `build_meta()` и `load_partition()` теперь case-insensitive сопоставляют фактические колонки драйвера с exact-case `output_columns` из плана и затем проектируют результат к публичным именам.
- Устранен источник `Metadata mismatch found in from_delayed` после exact-case Oracle query aliases: type hints теперь применяются даже если `pandas/oracledb` вернул колонки в другом регистре, а `build_meta()` больше не создает пустые `float64`-колонки через `reindex`.
- Добавлены unit-регрессии на Oracle-like case drift для `build_meta()` и `load_partition()` в `tests/unit/core/db/read_v3/test_executor_sql.py`; также подтвержден зеленый прогон `read_v3` executor/query-planner/node metadata и `test_dask.py`.

### 2026-04-21 18:11:37
- Исправлен Oracle metadata type mapping в `core/types/data_type.py`: `DataType.from_type(...)` теперь корректно распознает `NUMBER(...)`, `NUMERIC`, `BINARY_DOUBLE`, `BINARY_FLOAT`, `DOUBLE`, `REAL`, а также Oracle string/date типы без деградации в `UNKNOWN`.
- Добавлены unit-тесты `tests/unit/core/types/test_data_type.py` на Oracle type repr и регрессия в `tests/unit/src/nodes/extract/test_read_query_from_db_v3.py`, подтверждающая, что `ReadQueryFromDBV3.infer_metadata()` больше не возвращает `UNKNOWN` для `DATE`, `NUMBER(18,4)`, `VARCHAR2` и `BINARY_DOUBLE`.
- Попытка применить фикс в рантайме через перезапуск `task_worker` через `dvt_mcp.restart_service` не удалась из-за timeout PyCharm plugin, поэтому для фактического обновления metadata cache проекта требуется успешный перезапуск worker и повторный metadata/full запуск проекта.

### 2026-04-21 18:42:19
- Добавлена поддержка точечных исключений в `RULES` хука `scripts/.pre_commit/check_import_boundaries.py`.
- Для сервиса `services/dvt_mcp` разрешены импорты из `services.gateway.routes.impl`.
- Добавлен unit-тест на логику исключений и ограничение области действия исключения.

### 2026-04-21 19:01:35
- Обновлен job `write_merge_summary_b24` в `.gitlab-ci.yml`: после генерации merge summary теперь выполняется конвертация Markdown в BB-code через новый скрипт `scripts/.ci/markdown_to_bbcode.py`, а в артефакты добавлен итоговый `summary.bbcode.txt`.
- Переведены инструкции merge-summary агента и prompt `.ci/opencode/write_merge_summary.toml` с BB-code на Markdown, а также добавлено требование указывать внутренние сущности в формате `path/to/file:<entity_name>`.
- В `scripts/.ci/run_opencode.py` добавлен режим `markdown_sections`, в unit-тесты добавлены проверки для нового режима и конвертации Markdown в BB-code.

### 2026-04-22 12:26:59
- Добавлена полноценная backend-поддержка структурных JSON metadata: модели структуры JSON, inference дерева/схемы, flatten candidates и интеграция в общий `get_metadata(...)` flow.
- Добавлена backend-нода `JSON Editor` с поддержкой `record_path`, `meta_paths`, `explode_paths`, `keep_json_paths`, `exclude_paths`, auto-detect record source и ограничением `max_rows`.
- Добавлены unit-тесты на JSON metadata inference, dispatch JSON metadata и поведение `JSON Editor` в ключевых ETL-сценариях.

### 2026-04-23 16:13:32
- Нода `HTTPRequest` получила явные поля Auth (`auth_type`, Basic/Digest/OAuth2, client certificate) и сборку параметров `requests` из этих input values.
- Добавлены unit-тесты на контракт `NodeDefinition`, приоритет OAuth2 над ручным `Authorization` и валидацию auth-настроек.

### 2026-04-23 17:36:28
- Переделан Auth-контракт ноды `HTTPRequest`: вместо отдельных `auth_*` input-полей используется единый вложенный input `auth` со schema-вариантами `none`, `basic`, `digest`, `oauth2`, `file_cert`.
- Обновлены unit-тесты на вложенную структуру auth, приоритет над ручным `Authorization` и обратную совместимость headers-only сценария.

### 2026-04-23 18:03:32
- В `HTTPRequest.auth` добавлена поддержка DVT expression/variable payload во вложенных строковых полях (`username`, `password`, `token`, `cert_file_path`, `key_file_path`).
- Добавлены регрессионные тесты, проверяющие валидацию и runtime-resolve Basic/OAuth2 auth-полей из переменных.

### 2026-04-21 19:21:10
- Скорректирован конвертер `scripts/.ci/markdown_to_bbcode.py`: inline Markdown-код теперь переводится в `[B]...[/B]`, а fenced code block сохраняется как `[CODE]...[/CODE]`.
- Обновлены unit-тесты `tests/unit/scripts/test_markdown_to_bbcode.py` под новое поведение и добавлена защита от ложного форматирования подчёркиваний внутри inline-кода.

### 2026-04-22 12:42:45
- Модуль `core/db/read_v3` отвязан от удаленного `core/db/read_v2`: локально перенесены спецификация grouping, builder сегментов и вспомогательные утилиты для временных и packed-сегментов.
- Планировщики `read_v3` и unit-тесты переведены на новые локальные grouping-компоненты без изменения внешнего API `read_v3`.
- Из `src/nodes/testing/read_benchmark_db_nodes.py` удалены benchmark-ноды V2 и оставшиеся импорты `read_v2`.
- Обновлена документация `core/db/read_v3/README.md` под новую внутреннюю архитектуру grouping.

### 2026-04-22 14:04:01
- Исправлено Oracle-экранирование result columns в `read_v3`: простые идентификаторы в нижнем/верхнем регистре больше не оборачиваются в кавычки, поэтому чтение таблиц и `service_name`-сценарии снова работают корректно.
- Обновлены unit-тесты для `OracleDialect.quote_result_column` и проверка SQL в `tests/unit/core/db/read_v3/test_executor_sql.py`.
- Перепроверены unit-тест `tests/unit/core/db/read_v3/test_executor_sql.py`, точечные Oracle integration tests и полный integration suite — все проходят.

### 2026-04-22 14:18:35
- Дореализована нода `ConvertVariablesToDataFrame`: добавено преобразование входных переменных в однострочный `dask.DataFrame`, нормализация `VariableOutput`, поддержка metadata-режима и защита от unresolved-значений в полном выполнении.
- Добавлен экспорт ноды в `src/nodes/transform/__init__.py` и unit-тесты на скалярные типы, списки и metadata-режим.

### 2026-04-22 17:11:23
- В ноде `SaveParquet` добавлен мягкий fallback из режима `append` в `create`, если parquet-dataset по целевому пути еще не существует.
- Добавлена проверка существования dataset через Dask/PyArrow-совместимое разрешение файловой системы и обновлено логирование `requested_mode`/`effective_mode`.
- Расширены unit-тесты для сценариев fallback, обычного append, create/overwrite без existence-check и проброса ошибок проверки dataset.

### 2026-04-22 17:58:55
- Добавлен Markdown-план презентации по промежуточному результату проекта Merlion в `tmp/merlion/plan_presentation_merlion_intermediate_demo.md`.
- План описывает структуру слайдов, рекомендуемые визуалы и тезисы для выступления.

### 2026-04-22 18:18:02
- Добавлен PlantUML-файл первого слайда презентации Merlion в `tmp/merlion/presentation_1/slide_01_title_architecture.puml`.
- Схема отражает титульный архитектурный контур: источник данных, DVT pipeline и RAW layer.

### 2026-04-22 18:26:35
- Уточнен файл `tmp/merlion/presentation_1/plan_presentation_merlion_intermediate_demo.md`.
- План презентации переписан в прикладной формат: для слайдов со 2-го и далее добавлены точные заголовки, точный текст на слайдах, конкретные требования к скриншотам и видимым колонкам.

### 2026-04-22 18:32:01
- Добавлен набор PlantUML-файлов для презентации Merlion в `tmp/merlion/presentation_1`.
- Созданы схемы для слайдов 2, 3, 4, 9, 11, 12 и 13, где в презентационном плане требовались диаграммы и layout без продуктовых скриншотов.

### 2026-04-23 14:48:17
- Добавлен общий слой выполнения SQL-запросов для `read_v3`, который использует `clickhouse_connect` для ClickHouse и SQLAlchemy connection для остальных диалектов.
- `ReadQueryFromDBV3`, планирование, группировка, executor и извлечение метаданных переведены с `pd.read_sql_query` на общий runner, чтобы ClickHouse-запросы с `%` не падали на DBAPI-подстановке.
- Gateway-утилита метаданных SQL-запросов переиспользует общий ClickHouse introspection вместо отдельного точечного обхода.

### 2026-04-24 15:57:21
- Ограничено время проверки подключений в `services/dvt_mcp/operations.py`: `create_db_connection(check=true)` и `check_db_connection` теперь возвращают timeout-ошибку вместо долгого зависания.
- Исправлено создание transient DBConnection в `check_db_connection` без дублирования `organization_id`.
- Добавлены unit-тесты для timeout-сценариев `dvt_mcp` и обновлено описание возможностей в `AGENTS.md`.

### 2026-04-27 11:44:14
- Обновлены GitLab CI job-файлы для dev-цепочки: `build`, `unit_tests` и `deploy_dev` переведены на `needs`, а `build` теперь явно зависит от `cleanup_dev`.
- Это позволяет `write_merge_summary_b24` выполняться параллельно и не блокировать сборку, unit-тесты и dev-деплой по барьеру стадий.

### 2026-04-27 12:38:40
- Исправлен `core/db/read_v3/executors/sql.py`: для пустых результатов чтения добавлено восстановление схемы по `ReadV3Plan`, чтобы ClickHouse не терял колонки при построении meta.
- Исправлен `src/nodes/transform/df_join.py`: ключи `left_on/right_on` теперь нормализуются в списки, поэтому join корректно работает и при строковых значениях.
- Добавлен регрессионный unit-тест `tests/unit/src/nodes/transform/test_df_join.py` на join со строковыми ключами.

### 2026-04-27 12:46:57
- В GitLab CI обновлена зависимость job `build` от `cleanup_dev` в файле `.ci/gitlab/jobs/02-build-test.yml`.
- Жесткий `needs` заменен на `needs` с `optional: true`, чтобы pipeline не падал, если `cleanup_dev` не создается по условиям конфигурации.

### 2026-04-27 18:00:43
- Проектные переменные переведены на typed-формат хранения `type/value/is_list_type` в `Project.variables`.
- Обновлены HTTP и internal схемы, CRUD и gateway route-ы project variables, а также нормализация `variables` в обычном CRUD проекта.
- В runtime добавлен совместимый raw-view `project_variables.raw_values`, чтобы expression-резолв и Python/code-ноды продолжали получать обычные значения без поломки существующих сценариев.
- Добавлены и обновлены unit-тесты для route-ов, internal-схем, сериализации `DATETIME/TIMEDELTA`, `TaskInternal` и `ExecutePython`.

### 2026-04-30 16:05:22
- Добавлен отчет-ревью модуля `src/modules/licensing` в `tmp/reviews/licensing-review-20260430-160311.md`.
- В отчете зафиксированы архитектурные проблемы DDD-lite, runtime-баги, дублирование со старым licensing-слоем и рекомендации по улучшению.

### 2026-04-29 17:38:40
- Проведен рефактор integration test infrastructure.
- Добавлены `tests/integration/fixtures/settings.py` и `tests/integration/fixtures/gateway_live.py` для централизации env, общих live gateway fixtures и единых тестовых настроек.
- Переписан `tests/integration/fixtures/dvt_prod_containers.py`: убраны фиксированные sleep, добавлены детерминированные readiness checks и унифицированы env для DVT контейнеров.
- Gateway live integration тесты переведены на shared bootstrap/login fixtures, выровнены `docker_required` markers.
- `tests/integration/src/pipeline/test_processor.py` сокращен через общие helper'ы и получил явный timeout на `processor.process()`, чтобы S3-сценарии больше не зависали бесконечно в CI.

### 2026-04-29 19:12:39
- Добавлен неблокирующий post-deploy flow для интеграционных тестов на ветке `dev`.
- После `deploy_dev` теперь запускается child pipeline `.ci/gitlab/child-pipelines/dev-postdeploy-integration.yml` с отдельными шагами сборки prod-образов и интеграционных тестов.
- Для child pipeline включена автоотмена устаревших прогонов через `workflow.auto_cancel.on_new_commit: interruptible`, а job `integration_tests_dev` сериализован через `resource_group`, чтобы одновременно не выполнялось больше одного post-deploy integration test прогона.

### 2026-04-30 14:14:49
- Исправлен child pipeline `.ci/gitlab/child-pipelines/dev-postdeploy-integration.yml`: добавлен `before_script` с копированием `.env` из `$DOTENV_FILE`.
- Без этого post-deploy child pipeline запускал сборку prod-образов без подготовленного `.env`, из-за чего `pip download` в Docker-сборке запрашивал интерактивную авторизацию и падал с `EOFError`.

### 2026-04-30 14:20:30
- `write_merge_summary_b24` переведен в неблокирующий post-deploy режим.
- Тяжелая генерация merge summary вынесена из основного pipeline в child pipeline `.ci/gitlab/child-pipelines/merge-summary.yml`.
- В основном pipeline добавлена стадия `post_deploy_async`, где `write_merge_summary_b24` теперь работает как быстрый trigger-job с `when: always`, поэтому summary запускается после участка `deploy_dev`, не блокирует основной flow и не отменяет предыдущие summary-прогоны.

### 2026-04-30 14:22:17
- Улучшена читаемость GitLab pipeline для асинхронных post-deploy операций.
- Trigger-job для merge summary переименован в `write_merge_summary_trigger`, trigger-job для post-deploy integration — в `post_deploy_integration_dev_trigger`.
- Оба неблокирующих trigger-job теперь находятся в стадии `post_deploy_async`, чтобы в графе pipeline было явно видно fire-and-forget блок после `deploy_dev`.

### 2026-04-30 15:42:18
- Post-deploy integration flow для `dev` перенесен на отдельный runner `DVT-e2e-tests-stand`.
- В child pipeline `.ci/gitlab/child-pipelines/dev-postdeploy-integration.yml` jobs `build_prod_for_dev_integration` и `integration_tests_dev` теперь используют tag `DVT-e2e-tests-stand`.
- Основной runner `DVT` оставлен только для `deploy_dev` и быстрого trigger-job, а сборка prod-образов и сами интеграционные тесты выполняются на отдельной тестовой машине.

### 2026-05-04 13:30:52
- Добавлен repo-local skill `.codex/skills/module-context-builder` для создания и редактирования bounded context модулей в `src/modules`.
- Добавлены инструкции `SKILL.md`, reference-файл с правилами слоёв `domain/flow/infra` и anti-patterns, а также скрипты `scaffold_module.py` и `audit_module.py` для генерации каркаса и проверки структуры модулей.

### 2026-05-04 16:23:17
- Усилена нода `ExecuteProject`: добавлено разворачивание nested awaitable/Future из `enqueue_project_task_for_node` и `wait_for_task_terminal_state`, а также явная проверка наличия непустого `task_id` у результата.
- Добавлены интеграционные тесты `tests/integration/src/nodes/tool/test_execute_project.py`, которые воспроизводят сценарий с возвратом `Future` вместо объекта дочерней задачи и проверяют поведение `wait_for_completion` через `PipelineProcessor`.

### 2026-05-04 17:22:04
- Исправлена инициализация Fernet для `db_connection` в `gateway`: при старте `services/gateway` теперь заполняется `db_connection.extension_config.fernet`, поэтому сохраненные `db_connection` расшифровываются в процессе Gateway так же, как в `task_worker`.
- Добавлен unit-тест `tests/unit/services/gateway/test_lifespan.py`, который проверяет установку runtime-ключа Fernet для Gateway и предотвращает регрессию с проверкой `/api/db-connections/check-connection/{id}`.

### 2026-05-05 12:41:30
- Улучшена наблюдаемость heartbeat воркеров в orchestrator: добавлены постоянные структурированные логи подписки, сводки по heartbeat-окну, предупреждения о задержанных heartbeat, а также события регистрации, восстановления и перевода воркеров в offline со служебными метаданными.
- Расширены модели статусов воркеров и ответ `system/services-stats`: теперь для воркеров отдаются `worker_id`, `status`, время первого обнаружения, последнее время heartbeat, время последнего изменения статуса, `offline_since` и возраст heartbeat, включая ранее виденных offline-воркеров с последней телеметрией.
- Обновлен расчёт gateway-метрики живых воркеров, чтобы учитывать только воркеры со статусом `online`, и добавлены unit-тесты на новый payload system stats и liveness по времени фактического получения heartbeat.

### 2026-05-05 15:15:09
- В CI/CD-разделе релизного потока разделено предупреждение перед релизным деплоем для `rc` и стабильных тегов.
- Для `rc`-тегов `notify_demo_prod_update` теперь отправляет отдельное сообщение только про обновление DEMO, а для стабильных релизов сохранено сообщение про DEMO и PROD.
- Добавлен шаблон `.ci/b24_messages/demo_update_warning_message.toml`.

### 2026-05-06 16:09:52
- Роут `GET /projects/scheduler/scheduled` в Gateway обогащен историей scheduler-запусков из `tasks`: добавлены `last_run_*` поля и `recent_runs` для UI.
- Добавлен отдельный query-use-case для батчевой выборки последних scheduler-запусков по `project_id`.
- Исправлено сохранение причин ошибок выполнения: `PipelineProcessor` теперь возвращает `error_message`, а worker пишет в `tasks.message` реальный текст ошибки вместо общего сообщения.

### 2026-05-06 17:44:06
- Поле `next_run_time` убрано из write-path расписаний: backend больше не принимает его как управляющий параметр в create/patch запросах scheduler.
- `next_run_time` оставлено только в response-модели для отображения на UI.
- Добавлены тесты, подтверждающие, что лишний `next_run_time` от старого клиента игнорируется и не влияет на запуск задачи.

### 2026-05-06 18:00:52
- В `ProjectSchedulerManager.schedule_project` восстановлена фактическая прокидка optional-аргумента `next_run_time` в `_schedule_project_in_memory`, чтобы задел на будущий сценарий явного первого запуска был рабочим.
- Текущий write-path scheduler по-прежнему не подает `next_run_time` из API, поэтому немедленный запуск от UI не возвращен.

### 2026-05-06 16:31:23
- Добавлена продуктовая поддержка top-level CTE (`WITH ... SELECT`) для `ReadQueryFromDBV3` на MSSQL через общий слой композиции query-mode в `read_v3`.
- Добавлена ранняя валидация и понятная ошибка для неподдерживаемых MSSQL batch-скриптов (`DECLARE`, temp tables, `EXEC`, несколько statement'ов).
- Обновлены unit/integration тесты и документация `read_v3` по контракту query-mode для MSSQL.

### 2026-05-07 11:19:45
- Добавлены unit-тесты для `services/gateway/routes/project/cache/helpers.py:clear_data_cache`.
- Покрыты сценарии очистки кэша по списку `node_ids`, очистки кэша всего проекта и случая с пустым индексом без вызова удаления из data cache.
- Проверен запуск нового тестового модуля: тесты проходят успешно.

### 2026-05-07 11:28:00
- Переписаны unit-тесты для `services/gateway/routes/project/cache/helpers.py:clear_data_cache` без использования mock-менеджеров.
- В тестах задействованы реальные `LocalCacheManager` и `LocalIndexManager` с проверкой фактического состояния cache/index после очистки.
- Повторный запуск тестового модуля завершился успешно.

### 2026-05-07 11:51:42
- Добавлены integration-тесты для `services/gateway/routes/project/cache/helpers.py:clear_data_cache` с реальными `RedisCacheManager` и `RedisIndexManager` поверх Valkey/Testcontainers.
- Покрыты сценарии очистки кэша по списку `node_ids`, очистки кэша всего проекта и случая с пустым индексом при сохранении нерелевантного cache.
- Новый integration-модуль успешно запущен напрямую через `pytest` вне sandbox: тесты проходят.

### 2026-05-07 12:05:50
- Исправлена очистка project data cache для реальных типов индексных ключей: `clear_data_cache` теперь удаляет записи и данные по `PDFKey`, `JSONKey`, `DDFMetaKey` и legacy `CommonOutputKey`, а для выборочной очистки нод дополнительно убирает старые `node_output:*` meta-ключи DataFrame.
- Добавлена индексация meta DataFrame через `DDFMetaKey` в `DFOutputBaseNode` и расширены unit-тесты на очистку кеша и сохранение meta-index для DataFrame output.

### 2026-05-07 15:16:02
- Добавлена поддержка истории LLM-отчетов в GitLab CI через Generic Package Registry: новые скрипты `scripts/.ci/llm_history_registry.py`, `scripts/.ci/prepare_llm_history_context.py` и `scripts/.ci/publish_llm_history.py` публикуют итоговые отчеты и подмешивают в контекст последние записи из той же линии поставки.
- Обновлены LLM-джобы в `.gitlab-ci.yml`, `.ci/gitlab/child-pipelines/merge-summary.yml`, `.ci/gitlab/jobs/01-changelog.yml` и `.ci/gitlab/01-templates.yml`: для `merge summary`, `changelog` и `failure analysis` теперь собирается history-bundle и после успешной генерации публикуется финальный отчет.
- Обновлены промпты и agent-instructions в `.ci/opencode/*` и добавлены unit-тесты `tests/unit/scripts/test_llm_history_registry.py`, `tests/unit/scripts/test_prepare_llm_history_context.py`, `tests/unit/scripts/test_publish_llm_history.py`.

### 2026-05-07 18:08:43
- Исправлен сбой в `DataFrameJoin` при объединении с правой веткой после `drop_duplicates()`, когда dask сохранял некорректную internal partition-mapping metadata со значением `None` и падал на переименовании конфликтующих колонок.
- Добавлен регрессионный unit-тест на сценарий join по `PartnerHolding -> TITLE` с конфликтующей колонкой `region` на правой стороне.

### 2026-05-07 18:34:33
- Исправлен вызов `get_db_connections_by` в `services/gateway/deps/db_connection.py`: `session` теперь передается позиционно, а access-control фильтры — через `*filters`, что устраняет `TypeError: got multiple values for argument 'session'` в зависимостях Gateway.
- Обновлен `src/crud/db_connection/read.py`: дополнительные SQLAlchemy-фильтры перенесены в `*additional_filters` перед keyword-only параметрами и исправлена сборка условий с `append(...)` на `extend(...)`.
- Добавлен unit-тест на сценарий вызова `get_db_connections_by(session, *filters, connection_id=..., is_deleted=...)` с проверкой применения дополнительных фильтров.

### 2026-05-08 17:00:12
- Подготовлен план внедрения иерархии папок проектов, пагинации списка проектов и вывода последних scheduler-запусков.
- План сохранен в `tmp/project_crud_folders_pagination_last_runs_plan.md`.

### 2026-05-08 17:12:26
- Реализована иерархия папок проектов: добавлена модель `ProjectFolder`, поле `folder_id` у проектов, миграция и API для создания, обновления, удаления и постраничного чтения содержимого папок.
- Добавлена выдача последних пяти scheduler-запусков проекта в project CRUD responses и покрытие unit-тестами для папок, пагинации и last_runs.

### 2026-05-08 17:15:13
- Исправлена логика `last_runs` в project CRUD: последние запуски проекта теперь выбираются без фильтра по `TaskSource.SCHEDULER`.
- Добавлен общий CRUD-helper для последних запусков проекта, при этом scheduler-specific helper для расписаний сохранен без изменения.

### 2026-05-12 19:17:23
- В ответ папок проектов добавлено поле `user_email`, аналогичное полю в ответах проектов.
- Обновлена сборка `ProjectFolderReadSchema` в project CRUD и тесты для проверки `user_email` в folder responses.

### 2026-05-12 19:40:17
- Добавлен endpoint `GET /projects/search` для поиска проектов по вхождению текста в название с пагинацией и соблюдением ACL пользователя.
- Поиск поддерживает фильтр по папке проекта и возвращает проекты в том же read-формате, включая `last_runs`.

### 2026-05-13 12:21:19
- Обновлен `GET /projects/search`: поиск теперь возвращает как проекты, так и папки по вхождению текста в название.
- Добавлен параметр `item_type=all|folder|project`, удален публичный фильтр `store_enabled`, сохранены ACL и пагинация.

### 2026-05-13 12:46:27
- Проведен рефактор project CRUD routes: реализация бизнес-логики и сборки ответов вынесена в `services/gateway/routes/impl/project.py`.
- `services/gateway/routes/project/crud.py` оставлен тонким слоем FastAPI-маршрутов и зависимостей без изменения публичного API.

### 2026-05-12 11:18:16
- Подготовлен документ `tmp/dvt_patch_system_design.md` с проектированием системы срочных патчей для DVT.
- Описаны bounded context `patching`, формат `.dvtpatch`, механика overlay/image override патчей, процессы для разработчика и клиента, а также рекомендации по rollout и rollback.

### 2026-05-12 13:19:46
- В `src/nodes/tool/execute_project.py` добавлена расширенная диагностика для nested awaitable в `_await_nested_result()`: логируются тип awaitable, идентификаторы event loop/future, состояние future и усеченный `repr` при ошибке.
- В `src/crud/graph/common.py` заменена нормализация `GraphNode` через `model_dump()->model_validate()` на `model_validate(..., from_attributes=True)`, чтобы убрать Pydantic serializer warnings и лишнюю сериализацию.
- Добавлена миграция `0047_normalize_graph_node_input_value_type_keys.py` для рекурсивной очистки legacy-ключа `dvt_type` в `graph_nodes.input_values` с переводом в canonical `__dvt_type` и обратимым downgrade.
- Добавлены unit-регрессии для диагностического логирования `ExecuteProject`, для нормализации graph CRUD без serializer warnings и для upgrade/downgrade новой миграции `0047`.

### 2026-05-12 13:39:15
- В `src/crud/graph/common.py` исправлена нормализация `GraphNode` после регрессии с `MissingGreenlet`: вместо `model_validate(..., from_attributes=True)` используется column-only payload из уже загруженных ORM-колонок, что исключает lazy-load relationships в async-контексте.
- Подтверждено точечными unit-тестами, что `get_graph_by()` сохраняет typed-нормализацию `input_values` без Pydantic serializer warnings и без обращения к ORM relationships.

### 2026-05-13 13:31:18
- В `WorkerIDManager` добавлена генерация HWID через `src.security.hwid` при отсутствии или пустом файле `hwid.id`.
- Добавлен безопасный ленивый импорт генератора с fallback на прежнюю локальную логику по `MachineGuid`/`machine-id`/`uuid`, чтобы сбои в `src.security.hwid` не роняли запуск воркера.
- Добавлены unit-тесты на чтение существующего HWID, автогенерацию, Docker-сценарий и fallback-пути.

### 2026-05-14 12:44:11
- Подготовлен markdown-отчет по ревью модуля `src/modules/pipeline_cache` и проверке готовности к замене legacy-системы кеширования.
- Отчет сохранен в `tmp/reviews/pipeline_cache_review_2026-05-14.md`.

### 2026-05-14 13:28:29
- Переведена backend-система кеширования на модуль `src/modules/pipeline_cache` без legacy-слоя совместимости.
- Gateway и task worker переведены на новый runtime и Redis keyspace `pipeline_cache/*`, `PipelineProcessor` и cache-aware node output-слой обновлены на новые store/index abstractions и fingerprint helpers.
- Удалены пакеты `src/caching`, `src/managers/cache_manager`, `src/managers/index_manager`, обновлены unit/integration тесты и Redis-интеграции под новый модуль.

### 2026-05-14 13:51:18
- Завершено переименование legacy-терминов кеширования после миграции на `src/modules/pipeline_cache`.
- В runtime и DI заменены `cache_manager`/`index_manager` на `data_store`, `data_index_store`, `metadata_store`, `metadata_index_store`; обновлены `PipelineProcessor`, node base mixins, gateway/task worker dependencies и route-level wiring.
- Тесты и test doubles переведены на новый словарь имен, подтвержден проход unit и integration наборов для renamed cache store API.

### 2026-05-13 17:02:59
- Подготовлен начальный архитектурный план внедрения AI-анализа логов выполнения проекта DVT.
- План сохранен в `tmp/ai_log_analysis_initial_plan.md` и включает варианты интеграции, требования к конфиденциальности, redaction, OpenRouter/provider abstraction, bug report flow и этапы rollout.

### 2026-05-13 17:15:29
- Обновлен план `tmp/ai_log_analysis_initial_plan.md` с учетом продуктовых решений по AI-анализу логов.
- Зафиксированы ограничения MVP: только открытый контур, ручной запуск из UI, отсутствие user-facing context preview, генерация баг-репорта как Markdown/text без внешней отправки и отсутствие локальных моделей на текущем этапе.

### 2026-05-13 17:20:10
- Дополнен план `tmp/ai_log_analysis_initial_plan.md` новыми решениями по внедрению AI-анализа логов.
- Зафиксированы installation-time признак открытого контура, хранение `OPENROUTER_API_KEY` encrypted в env и обязательное сохранение сгенерированного bug-report document в БД.

### 2026-05-13 17:24:25
- Уточнен план `tmp/ai_log_analysis_initial_plan.md` для тестового rollout AI-анализа логов.
- Зафиксировано, что на этапе MVP-testing фича включается только на `dev`, `demo` и `pre-prod`, в `prod` остается отключенной до готовности, а `OPENROUTER_API_KEY` задается через GitLab CI/CD variables.

### 2026-05-13 17:49:39
- Исправлена выборка `last_runs` для project CRUD: в историю проектов теперь попадают только запуски `ExecMode.FULL`, а `metadata_only` исключаются до ранжирования последних запусков.
- Обновлен unit-тест project routes, проверяющий, что более свежий `metadata_only` запуск не попадает в список последних запусков проекта.

### 2026-05-14 14:41:30
- В `tests/integration/src/pipeline/test_processor.py` заменены устаревшие DB read/write ноды на `ReadTableFromDBV3`, `ReadQueryFromDBV3` и `WriteDataFrameToDBV3`.
- Добавлены локальные helper-функции для V3-нод и предварительное создание таблиц через `CreateTable`, так как `write_v3` пишет только в существующие таблицы.

### 2026-05-14 15:14:41
- Доработана миграция `tests/integration/src/pipeline/test_processor.py` на V3-ноды: для `ReadQueryFromDBV3` настроены совместимые `partition_col`/`partition_grouping`, а сравнения в тестах адаптированы к индексации и порядку строк после V3-чтения.
- Подтверждено прохождение `pytest tests/integration/src/pipeline/test_processor.py -q` — все 7 тестов успешны.

### 2026-05-14 15:38:06
- Обновлен `.dockerignore`: исключены `extensions/`, `hwid/` и `*.env` из Docker build context.
- Это снижает нагрузку на BuildKit в тестовой сборке `tester_unit` и убирает из контекста файлы, не нужные для сборки.

### 2026-05-14 16:41:04
- Подготовлен отчет по причинам высокой утилизации диска на GitLab Runner `DVT` и сохранен в `tmp/dvt_disk_utilization_report.md`.
- В отчете разобраны CI/CD jobs, Docker/Compose-конфиги, тестовая инфраструктура, backend-скрипты и предложены диагностические команды и безопасные патчи.

### 2026-05-15 12:30:32
- Создан bounded context `src/modules/file_storage` для работы с файловыми хранилищами.
- Логика storage API вынесена из `services/gateway/routes/storage` в use case/provider/gateway adapters с поддержкой `s3`, `ftp` и `sftp`.
- Добавлены generic-схемы `src/schemas/http/storage`, новый dependency `services/gateway/deps/file_storage.py`, proxy-эндпоинты загрузки/скачивания через Gateway и тесты для path normalization, provider resolution и storage routes.

### 2026-05-15 12:39:43
- Перенесена реализация S3-клиента из `src/managers/s3.py` в bounded context `src/modules/file_storage/infra/clients/s3.py`.
- `src/modules/file_storage` и legacy storage-deps больше не зависят напрямую от старого util-слоя; `src/managers/s3.py` оставлен как compatibility wrapper над новым `S3StorageClient`.
- Проверена работоспособность таргетированными unit-тестами для `file_storage` и gateway storage routes.

### 2026-05-15 13:22:42
- В модуле `src/modules/file_storage` добавлены операции `rename` и `move` для файлов и директорий через новые use case и реализации для S3/FTP/SFTP.
- Маршруты `services/gateway/routes/storage` расширены новыми endpoint'ами `/storage/path/rename` и `/storage/path/move`, добавлены входные схемы и unit-тесты для нового API.

### 2026-05-15 20:51:36
- Исправлена работа FTP-хранилищ без поддержки команды `MLSD` в `src/modules/file_storage`: добавлен fallback на `NLST`/`CWD`/`SIZE`/`MDTM` для листинга и рекурсивного удаления директорий.
- Добавлен unit-тест на сценарий с FTP-сервером, который отвечает `500 Unknown command` на `MLSD`.

### 2026-05-15 20:56:22
- Исправлен ложноположительный успех `folder/create` для FTP-хранилищ: `src/modules/file_storage/infra/gateways/ftp.py` больше не подавляет ошибки `MKD`, если директория реально не создана.
- Добавлен unit-тест на сценарий, когда FTP-сервер возвращает отказ при создании каталога, и Gateway должен получить ошибку вместо `200`.

### 2026-05-15 21:45:39
- Удалены входы `filename` из нод `SaveCSV`, `SaveExcel` и `SaveParquet`; сохранение переведено на единый вход `path` с общей нормализацией расширений.
- Добавлена миграция `0049_remove_filename_from_save_file_nodes` для переноса `graph_nodes.input_values` со старого контракта `{path, filename}` на новый `{path}` с проверкой неподдерживаемых link-сценариев.
- Обновлены unit/integration тесты и добавлены новые тесты для нормализации target path и миграции удаления `filename`.

### 2026-05-18 15:44:12
- Добавлен аналитический отчет `tmp/conditional_branching_report.md` по фиче условного ветвления пайплайна.
- В отчете описаны оценка идеи, плюсы и минусы, альтернативы реализации, рекомендуемая архитектура и вывод о том, что полный перенос `src/pipeline` в bounded context в `src/modules` до внедрения фичи делать преждевременно.

### 2026-05-18 16:05:39
- Добавлен отдельный отчет `tmp/signal_router_branching_report.md` по фиче условного ветвления через router-ноду на сигнале.
- В отчете разобраны текущие ограничения runtime для `signal_in/signal_out`, причины, по которым одной новой ноды недостаточно, и предложен практический дизайн первой версии с бинарной `if/else` router-нодой и processor-level семантикой активных/неактивных сигналов.

### 2026-05-18 16:37:16
- Реализована signal-router нода `ConditionalSignalRouter` для эксклюзивного ветвления пайплайна по условию.
- `PipelineProcessor` доработан для учета активности конкретных `signal`-выходов, добавлена семантика AND для `signal_in` и сохранена обратная совместимость через auto-activation обычного `signal_out`.
- Добавлены проверки на недопустимый rejoin веток роутера в один `signal_in` и запрет использования `ConditionalSignalRouter` как explicit target node.
- Покрытие дополнено unit-тестами для ноды, processor, validation и graph builders.

### 2026-05-18 17:14:52
- Доработан контракт нод для signal-routing: в `BaseNode` добавлен классовый флаг `CAN_BE_OUTPUT_NODE`, а `ConditionalSignalRouter` помечен как недопустимый explicit target через этот capability-флаг.
- Проверки в `src/pipeline/graph/builders.py` и `src/pipeline/validation.py` переведены с привязки к имени класса на использование `CAN_BE_OUTPUT_NODE`.
- В `src/pipeline/processor.py` проверка signal-output типов переведена со строковых литералов на Enum `IO`.

### 2026-05-20 13:14:08
- В ноде `ReadVariablesFromDB` изменена логика определения типа выходных переменных для режима `sql`: при наличии metadata тип колонки теперь имеет приоритет над infer по runtime-значению для scalar-переменных.
- Добавлены регрессионные unit-тесты на сценарии, где SQL metadata задает типы `BOOLEAN` и `INT`, а драйвер возвращает строковые значения.

### 2026-05-20 13:38:54
- В ноде `ReadVariablesFromDB` для режима `sql` добавлена нормализация имен колонок при сопоставлении `sql_variables` с результатом запроса и metadata описанием колонок (`strip` кавычек/скобок, сравнение без учета регистра).
- Исправлено получение имен колонок в preview-запросе через `result.keys()`, чтобы не итерироваться по строкам результата.
- Добавлены регрессионные unit-тесты на нормализованное сопоставление override-ключей и metadata-имен колонок.

### 2026-05-20 13:59:04
- Подготовлен отчет `tmp/dynamic_node_io_report.md` по системе динамических входов/выходов нод.
- В отчете разобраны варианты реализации, выбран подход с per-node resolved schema, выделены плюсы, минусы и риски, а также рекомендован поэтапный запуск через `ConditionalSignalRouter` как MVP и `ExecuteSQL` как следующий этап.

### 2026-05-20 18:15:35
- Добавлена opt-in поддержка field-mixin'ов в `node_dsl` через новый `NodeFieldsMixin` и расширение `BaseNodeMeta` для наследования `InputField`/`OutputField` из специальных mixin-классов.
- Добавлен пакет `src/node_dsl/node_mixins` и SQL-миксины для переиспользуемых полей и валидации SQL-кода.

### 2026-05-21 12:21:42
- Добавлен bounded context `src/modules/sql_validation` для policy-based структурной SQL-валидации через `sqlglot` с учетом dialect и детерминированных сообщений об ошибках.
- Обновлен `src/node_dsl/node_mixins/sql.py`: добавлен `SQL_VALIDATION_POLICY`, явный hook для dialect и корректный short-circuit для unresolved values.
- Добавлены unit tests для нового модуля и mixin-контракта, включая классификацию statement types, multiple statements, `RETURNING`/`OUTPUT`, syntax errors и dialect-specific parsing.

### 2026-05-21 13:34:20
- Дополнена миграция `0050_normalize_graph_node_input_value_sql_code`: добавлено переименование SQL-входов нод `query`/`sql_query`/`sql` в `sql_code` с учетом типа ноды, а также синхронное обновление `graph_edges.target_handle` для linked-входов.
- Добавлены unit-тесты на upgrade/downgrade и переименование edge handle для миграции `0050`.

### 2026-05-14 15:26:35
- Добавлена backend-фича AI analysis для упавших запусков проекта: создание запроса, polling, история запросов, сбор контекста проекта и интеграция с OpenRouter.
- Реализованы схемы, модель, CRUD, migration и unit-тесты с учетом role-scope, redaction секретов и фильтрации только full-запусков для last_runs.

### 2026-05-14 16:51:39
- Скорректирован публичный ответ AI analysis: из результата polling скрыты служебные поля OpenRouter (`model`, `openrouter_response_id`, `usage`, `finish_reason`, `raw_content`).
- Обновлен prompt AI analysis: модель теперь должна возвращать краткий `title` ошибки для отображения в UI, добавлен unit-тест публичной проекции результата.

### 2026-05-15 13:12:41
- Добавлен feature flag `DVT_DEV_ENABLE_AI_ANALYSIS` для AI-анализа ошибок задач: backend по умолчанию отключает AI endpoints и отдает состояние через `/system/features`.
- Переменная прокинута в `gateway` и `ui` services в compose-файлах; CI включает флаг только для dev, preprod и demo стендов.
- Добавлены unit-тесты для отключенного AI endpoint и публичного feature flags endpoint.

### 2026-05-15 13:16:14
- Исправлено имя runtime feature flag для AI-анализа на `DVT_ENABLE_AI_ANALYSIS`.
- В GitLab CI добавлен маппинг стендовых переменных: `DVT_DEV_ENABLE_AI_ANALYSIS`, `DVT_PREPROD_ENABLE_AI_ANALYSIS`, `DVT_DEMO_ENABLE_AI_ANALYSIS` передаются в сервисы как `DVT_ENABLE_AI_ANALYSIS`.
- Для UI service переменная передается как `DVT_ENABLE_AI_ANALYSIS` и `VITE_DVT_ENABLE_AI_ANALYSIS`; prod job не включает флаг.

### 2026-05-15 13:58:13
- Endpoint выдачи runtime-настроек переименован в `/system/runtime-config` с контрактом `features.ai_analysis`.
- Из compose-файлов удалена переменная `VITE_DVT_ENABLE_AI_ANALYSIS`; клиенты должны получать состояние AI-фичи через backend runtime config, а не через build-time Vite env.
- Обновлен unit-тест runtime config endpoint.

### 2026-05-15 14:00:52
- Удалена передача `DVT_ENABLE_AI_ANALYSIS` в `ui` service из compose-файлов.
- Флаг AI analysis теперь прокидывается только в `gateway`, а клиенты должны получать состояние через `/system/runtime-config`.

### 2026-05-15 16:33:30
- Добавлена стартовая документация для прототипа отдельного DVT AI Service в `tmp/ai-service`.
- Созданы `AGENTS.md` с правилами разработки сервиса и `CODEX_START_PROMPT.md` с подробным планом запуска новой Codex-сессии.

### 2026-05-18 15:12:03
- Логика AI analysis в Gateway переведена на внешний AI service вместо локального OpenRouter/prompt-контекста.
- Удалена сборка большого project context внутри DVT: Gateway теперь формирует минимальный payload, создает remote request в AI service и дополливает его статус/result в локальную историю `AIAnalysisRequest`.
- Обновлен `config.AI_ANALYSIS` под `AI_SERVICE_URL`/`AI_SERVICE_API_KEY`/poll timeout и переписаны unit-тесты маршрутов AI analysis под новый внешний контракт.

### 2026-05-18 17:49:36
- Рефакторинг AI-анализа логов в Gateway под внешний AI-сервис.
- Удалено поле `prompt` из модели, CRUD и миграции `0049`, локальное хранение сведено к минимальному контексту с `task_id`, `failed_node_id` и `ai_service_request_id`.
- В `services/gateway/routes/impl/ai_analysis.py` реализована надежная гибридная синхронизация: background-задача создает remote request и делает ограниченные попытки sync, а `GET` для non-terminal статусов выполняет authoritative refresh через AI-сервис.
- Сбор payload переведен на новый контракт AI-сервиса: добавлены `pipeline_context`, `analysis_context`, реальные task-scoped DB logs, traceback и определение DVT-модулей из traceback.
- Обновлены unit-тесты для create/get lifecycle, background sync и нового remote payload.

### 2026-05-19 12:12:00
- Проведен рефактор `services/gateway/routes/impl/ai_analysis.py` без изменения функциональности.
- AI-related логика разделена на отдельные модули: клиент внешнего AI-сервиса, parsing/helper-функции, сборка payload/context и mapping статусов/схем.
- Добавлен reusable helper `src/utils/repo_paths.py` для нормализации путей внутри репозитория.
- Обновлены unit-тесты для новой структуры модулей и добавлены точечные проверки extracted helper-ов.

### 2026-05-19 12:17:46
- Скорректирована структура рефактора AI analysis по замечанию: вместо набора файлов в `services/gateway/routes/impl` создан пакет `services/gateway/routes/impl/ai_analysis`.
- Внешний импорт `from services.gateway.routes.impl import ai_analysis` сохранен, внутренняя логика и helper-модули перенесены внутрь пакета.
- Удалены промежуточные файлы `ai_analysis_*.py` из корня `impl`, обновлены тестовые импорты под пакетную структуру.

### 2026-05-19 12:22:19
- Структура пакета `services/gateway/routes/impl/ai_analysis` приведена к более корректной форме: основная имплементация вынесена из `__init__.py` в `impl.py`.
- `__init__.py` оставлен тонким фасадом с re-export публичных entrypoint-ов для сохранения совместимости импортов.
- Обновлены unit-тесты под новую точку monkeypatch-а внутри `impl.py`, повторно подтверждено прохождение целевого набора тестов.

### 2026-05-19 12:24:02
- В `AGENTS.md` добавлено правило для Gateway route impl: при разрастании имплементации роута нужно создавать пакет с вспомогательными файлами вместо набора крупных модулей в одном файле.
- Зафиксировано соглашение, что основной файл такой пакетной имплементации должен называться `impl.py`, а `__init__.py` использоваться как тонкий фасад с re-export публичных entrypoint-ов.

### 2026-05-19 12:41:52
- Обновлена синхронизация истории AI-анализа в Gateway.
- Для `GET /ai/analyze` добавлен page-scoped refresh: backend под капотом синхронизирует все non-terminal записи только текущей страницы истории, обновляет локальную БД и возвращает уже освеженный список.
- Detail endpoint продолжает точечно синхронизировать одну запись, а background sync после create остается ускоряющей оптимизацией.
- Добавлены unit-тесты на синхронизацию только текущей страницы, отсутствие refresh для записей вне страницы и best-effort поведение при ошибке синхронизации одной записи.

### 2026-05-19 12:58:21
- AI analysis client переведен на batch-чтение через роут `/v1/analysis/requests`.
- Page-scoped refresh истории и точечный refresh запросов теперь используют batch API вместо отдельных GET по каждому request_id.
- Обновлены unit-тесты AI-analysis под новый контракт batch-ответа AI-сервиса.

### 2026-05-19 13:39:39
- Удален `selected_node_ids` из backend-контракта AI analysis: создание запроса теперь опирается только на `task_id`.
- Добавлено поле `failed_node_id` в `Task`, миграция БД и сохранение упавшей ноды из `PipelineProcessor`/task worker.
- Обновлено определение failed node для AI analysis: сначала по `Task.failed_node_id`, затем по логам задачи и текстовым fallback-полям.
- Добавлен orchestrator-backfill `failed_node_id` по `NodeExecutionStatusEvent(ERROR)` и обновлены unit-тесты для нового потока.

### 2026-05-19 13:44:52
- Исправлено создание `AIAnalysisRequest`: `user_id` теперь берется из `task.user_id`, а не из `access_scope.owner_user_id`, чтобы admin/global-access сценарии не сохраняли `NULL` в обязательное поле.
- Добавлен регрессионный unit-тест на создание AI analysis от имени admin для чужой задачи.

### 2026-05-19 13:47:02
- Исправлена сериализация payload для AI analysis: `pipeline_context.nodes[].input_values` теперь приводится к JSON-safe виду перед отправкой во внешний AI service.
- Добавлен регрессионный unit-тест на сериализацию input values ноды с `const`-значениями.

### 2026-05-19 13:48:02
- Исправлен порядок `pipeline_context.nodes` для AI analysis: failed node теперь принудительно ставится последним элементом списка, как требует внешний AI service.
- Обновлены unit-тесты на порядок узлов и сериализацию payload.

### 2026-05-19 14:41:52
- Синхронизированы контракты AI-анализатора логов с сервисом `denvic_ai`: добавлены строгие Pydantic-схемы запроса/ответов и typed-валидация в `src/clients/ai_analysis_client.py`.
- Маршрут и имплементация Gateway AI analysis переведены на явные схемы при сборке payload, обработке poll/batch ответов и выдаче `result` в HTTP response.
- Добавлены и обновлены unit-тесты для gateway AI analysis и клиента интеграции с проверкой строгой валидации контрактов.

### 2026-05-19 14:58:41
- Откатены изменения, связанные с `failed_node_id`: удалены поле из `Task`, поддержка в CRUD задач, передача через `pipeline.processor`, `task_worker` и `orchestrator`, а также удалена миграция `0050_add_failed_node_id_to_tasks.py`.
- В AI analysis больше не сохраняется и не вычисляется реальный `failed_node_id` для контекста запроса; для текущего внешнего контракта в `pipeline_context` оставлен временный synthetic placeholder.
- Обновлены unit-тесты под новый поток без `failed_node_id` в задачах и контексте AI analysis.

### 2026-05-19 15:43:55
- Для AI analysis вынесен `task_id` из JSON-поля `context` в явную колонку `ai_analysis_requests.task_id`: обновлены модель `AIAnalysisRequest`, CRUD и route impl Gateway.
- Изменена миграция `migrations/versions/0049_add_ai_analysis_requests.py`: таблица теперь создается с колонкой `task_id` и отдельным индексом по ней.
- Убраны чтение и запись `task_id` через `context`; `context` теперь используется только для вспомогательных данных вроде `ai_service_request_id`. Обновлены unit-тесты AI analysis под новое хранение.

### 2026-05-19 16:12:50
- В AI analysis request `ai_service_request_id` вынесен из JSON `context` в отдельное поле модели `AIAnalysisRequest`.
- Обновлена текущая миграция `0049_add_ai_analysis_requests.py`: добавлены колонка `ai_service_request_id` и индекс по ней.
- Исправлена gateway-имплементация AI analysis: чтение и запись remote request id теперь идут через явное поле, без хранения значимого идентификатора в `context`.
- Обновлены unit-тесты AI analysis под новое хранение идентификатора внешнего сервиса.

### 2026-05-19 16:28:54
- В AI analysis payload builder ограничена отправка логов во внешний сервис: исключены записи с уровнем `DEBUG`, добавлен лимит на последние 100 логов по задаче.
- Сохранено хронологическое упорядочивание логов в отправляемом payload.
- Добавлен unit-тест на фильтрацию `DEBUG`, ограничение до 100 записей и сохранение `traceback` даже если он находится в более старом логе.
- Заодно очищены устаревшие тестовые ожидания по полю `role` в `pipeline_context.nodes`, которого нет в текущем контракте AI analysis сервиса.

### 2026-05-20 13:05:32
- Исправлена интеграция AI Analysis с новым полем `title`.
- Поле `title` перенесено в `result` ответа AI-сервиса, добавлено как опциональная колонка в `ai_analysis_requests` и сохранение этого значения при синхронизации результата.
- Обновлены публичные схемы Gateway и миграция `0049_add_ai_analysis_requests.py`.
- Актуализированы unit-тесты для клиента AI Analysis, роутов Gateway и текущего поведения передачи логов без дополнительной фильтрации.

### 2026-05-20 15:14:08
- Синхронизирован контракт AI Analysis с новым полем `analysis_mode` в ответах AI-сервиса.
- Поле добавлено в `AIServiceAnalysisRequestReadSchema`, обновлены unit-тесты клиента и Gateway AI Analysis под новый payload batch/single poll и create response.

### 2026-05-20 17:29:30
- В AI analysis ограничена отправка логов в внешний сервис: теперь в payload попадают только последние 20 записей по задаче с сохранением хронологического порядка.
- Добавлена отдельная выборка `exception_traceback`, чтобы traceback не терялся, если он находится вне окна последних 20 логов.
- Обновлен unit-тест для проверки нового ограничения и сохранения traceback.

### 2026-05-22 12:12:43
- Добавлен новый bounded context `src/modules/sql_code_metadata` для структурного анализа SQL-кода, policy-based валидации и извлечения полного `SQLCodeMetadata`.
- Перенесена логика из `src/modules/sql_validation` без compatibility shim, обновлены импорты в `src/node_dsl/node_mixins/sql.py`.
- Переработан `services/gateway/routes/utils/sql_query_to_metadata.py`: route `/utils/sql-code-metadata` теперь использует новый use case и возвращает полный `SQLCodeMetadata`, включая `DataFrameMetadata` для `SELECT`, `RETURNING` и MSSQL `OUTPUT`.
- Добавлены и обновлены unit-тесты для нового модуля, SQL mixin и gateway utility route.

### 2026-05-22 15:08:11
- Перенесена memory-aware auto-оценка `npartitions` из legacy `core/db/read_v1` во внутренний модуль `core/db/read_v3` и встроена в planner'ы `table`/`query`.
- Упрощены ноды `ReadTableFromDBV3` и `ReadQueryFromDBV3`: legacy pre-planning и локальная query-эвристика удалены, planner теперь сам рассчитывает `npartitions`, если параметр не задан явно.
- Полностью удален пакет `core/db/read_v1` и его unit-тесты.
- Обновлен `core/db/read_v3/README.md`, добавлены unit-тесты для internal estimator/planner'ов и integration-проверки auto partitioning для V3-нод.

### 2026-05-25 10:47:13
- Подготовлен отчет ревью коммита `4e1eef4759b02b371b802758644a755062742bac` и сохранен в `tmp/review_4e1eef4759b02b371b802758644a755062742bac.md`.
- В отчете зафиксированы регрессия table-mode `read_v3`, ошибка авторазбиения на партиции, сломанный benchmark-узел и небезопасная сборка SQL в `_auto_partition.py`.

### 2026-05-25 11:23:44
- Исправлены регрессии `read_v3` после коммита `4e1eef4759b02b371b802758644a755062742bac`: унифицирован strict API planner'ов по параметру `min_rows_per_partition`, обновлены extract- и benchmark-ноды, тесты и README.
- Исправлен auto-partition estimator: расчет числа партиций теперь одновременно соблюдает memory-limit и row-cap, а fallback `COUNT(*)` для table-size estimation использует диалектное quoting имени таблицы.
- Добавлены и обновлены unit/smoke тесты для planner/executor/node-путей, включая проверку quoted `COUNT(*)` и корректного benchmark-path.

### 2026-05-25 12:02:52
- В ноде `src/nodes/tool/execute_sql.py` добавлено заполнение `output`, если SQL-запрос возвращает данные: `SELECT` читается в DataFrame через общий read_v3 runner, а `INSERT/UPDATE/DELETE ... RETURNING` выполняются в транзакции с чтением результирующих строк.
- В `process_metadata` для `ExecuteSQL` добавлено построение пустого `dd.DataFrame` по `dataframe_metadata`, полученной из SQL metadata extraction use case.
- Обновлены unit-тесты для сценариев `SELECT`, `RETURNING`, metadata-only и SQL без результирующего набора.

### 2026-05-25 14:39:03
- Переработана модель `DBMetadata`: добавлены иерархические слои `databases` и `schemas`, а также методы обхода и поиска таблиц.
- Обновлены sync/async загрузчики метаданных для PostgreSQL, MSSQL, MySQL, Oracle и ClickHouse с поддержкой пустых баз данных и схем.
- Адаптирован `ReadTableFromDBV3` и обновлены unit-тесты под новый контракт метаданных БД.

### 2026-05-27 12:58:34
- Добавлена backend-поддержка матричного JSON в `JSON Editor` и JSON metadata.
- Реализовано распознавание строк заголовков, генерация синтетических колонок `column_N`, нормализация `list[list[...]]` в `list[dict]`, а также warnings/statistics для коротких и длинных строк.
- Добавлены unit-тесты для metadata и `JSON Editor`, включая сценарии с header-row и synthetic fallback.

### 2026-05-27 17:10:23
- Для ноды `ExecuteProject` добавлен новый необязательный вход `target_project_name` для хранения snapshot-имени целевого проекта на стороне графа.
- Обновлены unit и integration тесты: подтверждено, что новое поле принимается нодой и не влияет на runtime-исполнение, которое по-прежнему использует только `target_project_id`.

### 2026-05-26 15:46:12
- В Gateway для маршрутов DBConnection добавлена поддержка явного задания `organization_id` и `user_id` для пользователей с ролью `SUPERADMIN` при create/update/upsert.
- Для ролей `ADMIN` и `USER` сохранена принудительная нормализация владельца соединения к текущему пользователю.
- Расширены HTTP-схемы `DBConnectionCreate`, `DBConnectionUpdate` и `DBConnectionUpsert`, добавлены unit-тесты на create/update/upsert сценарии с переопределением владельца и проверена совместимость route-тестами.

### 2026-05-26 17:44:51
- Добавлен рабочий сервис `demo_provisioning` с endpoint-ом `POST /bootstrap-demo-client`, клиентами для Gateway и Yandex Cloud, проверкой S3-доступа и best-effort rollback при частичных сбоях.
- Добавлены Docker/compose и GitLab CI изменения для сборки, публикации и demo-развертывания `demo_provisioning`.
- Добавлены unit-тесты для helper-логики и сценариев bootstrap/rollback сервиса `demo_provisioning`.

### 2026-05-26 17:59:06
- Добавлен `services/demo_provisioning/README.md` с кратким описанием назначения сервиса, его конфигурации, входных заголовков и пошаговой подготовкой Yandex Cloud для запуска bootstrap endpoint-а.

### 2026-05-26 20:56:53
- Дореализована нода `src/nodes/data_mock/db_connection.py`: добавлено построение mock `sa.Engine` с корректным `dialect` и `drivername` для `postgres`, `mysql`, `clickhouse`, `mssql`, `oracle` и `mongodb`, а также безопасная генерация metadata без реального подключения к БД.
- Добавлены unit-тесты для проверки резолва mock engine и metadata в `tests/unit/src/nodes/data_mock/test_db_connection.py`.

### 2026-05-26 21:11:56
- Расширена нода `src/nodes/data_mock/db_connection.py`: вместо пустых metadata добавлена генерация реалистичных mock-метаданных для `postgres`, `mysql`, `mssql`, `oracle`, `clickhouse` и `mongodb` с использованием билдера структур `DBMetadata`, приближенных к логике `core/metadata/db_metadata`.
- Для SQL dialect mock-метаданные теперь содержат правдоподобные базы, схемы, таблицы, представления, типы колонок, nullable, primary key и индексы; для `mongodb` добавлены коллекции в формате `DBMetadata`.
- Обновлены unit-тесты `tests/unit/src/nodes/data_mock/test_db_connection.py`: добавлены проверки структуры metadata и типов колонок для всех поддерживаемых `connection_type`.

### 2026-05-27 12:45:06
- Обновлен `services/demo_provisioning/README.md`: детализирован выпуск authorized key для provisioning service account через UI и YC CLI, добавлен пример структуры JSON-ключа и уточнена рекомендация по Base64-передаче в `X-YC-SA-Key`.
- Блок про права provisioning service account переписан на точный список ролей `storage.admin` и `iam.serviceAccounts.admin` с пояснением по scope и ограничению `storage.editor`.

### 2026-05-27 14:48:35
- Добавлен аналитический отчет `tmp/db_connection_1_0_0_migration_report.md` по совместимости DVT с новой версией библиотеки `db-connection`.
- В отчете зафиксированы ключевые несовместимости, покрытие типов подключений и детальный план миграции в стиле DDD-lite с ссылками на исходники DVT и новой библиотеки.

### 2026-05-27 21:07:38
- Обновлены unit-тесты `tests/unit/core/metadata/test_s3_metadata.py` под новый S3-контракт без `ConnectionManager`: тесты переведены на реальный `DBConnection` и мок `_build_s3_client`.
- Исправлены регрессии в S3 metadata после отвязки от `db_connection`: добавлен безопасный fallback для отсутствующего поля `verify`, восстановлена корректная обработка `prefix` в `load_s3_path_metadata` и устранено затирание `connection_prefix` в `load_s3_metadata`.

### 2026-05-27 21:26:12
- Отвязаны `core/metadata` FTP-функции от `db_connection`: `load_ftp_metadata` и `load_ftp_path_metadata` теперь работают от явных параметров подключения и сами поднимают FTP/FTPS клиент.
- В `src/modules/db_connection_v0_3/infra/mappers.py` добавлены `ftp_connection_to_metadata` и `ftp_connection_to_path_metadata`, а `GetExistFTPConnection` переведен на новый mapper.
- Добавлены unit-тесты для FTP metadata и mapper boundary, покрывающие маскировку строки подключения, чтение директории и anonymous credentials.

### 2026-05-27 22:25:13
- Обновлена логика `_wait_ws_task_result` в `tests/e2e/fixtures/gateway_e2e_runtime.py`: статус ошибки по `LOG_EVENT` теперь определяется только по уровням `ERROR` и `CRITICAL`, без ложного срабатывания на подстроку `failed` в debug-сообщениях.
- Добавлен регрессионный unit-тест `tests/unit/e2e/test_gateway_e2e_runtime.py`, который подтверждает игнорирование debug-сообщения `get_type_hints failed` и сохранение падения на явном `ERROR`-событии.

### 2026-05-28 12:32:30
- Исправлено сопоставление кириллических имен колонок при записи DataFrame в уже существующие SQL-таблицы через write_v3: для reflected-схем добавлено runtime-восстановление транслитерации к именам колонок таблицы.
- Добавлена защита от тихой записи строк только с NULL/default при полном несовпадении пользовательских колонок DataFrame со схемой таблицы.
- Расширены unit-тесты на сценарии транслитерации и явной ошибки при отсутствии совпадающих колонок.

### 2026-05-28 12:10:03
- Добавлен отдельный compose-файл `docker/docker-compose.demo-dev.yaml` для изолированного запуска `demo-provisioning` на `DVT Stand`.
- Из `docker/docker-compose.dev.yaml` удалено описание `demo-provisioning`, чтобы dev-стек и demo-stand deployment были развязаны.
- В GitLab CI добавлена джоба `deploy_demo_provisioning_dev`, которая запускается только на merge-коммите в ветку `dev`, собирает и поднимает `demo-provisioning` через отдельный compose-проект без `--remove-orphans`.
- Добавлено новое правило `.rules_merge_push_to_dev_only` и сообщение Bitrix24 для статуса этой джобы.
- Обновлен `services/demo_provisioning/README.md` под новый сценарий локального запуска и обновления сервиса на `DVT Stand`.

### 2026-05-28 12:28:59
- Исправлена джоба `deploy_demo_provisioning_dev` в GitLab CI: удалены self-reference переменные `DVT_DEMO_PROVISIONING_*` из блока `variables`, из-за которых в Docker Compose попадали буквальные значения вида `${DVT_DEMO_PROVISIONING_PORT}` и падал парсинг `hostPort`.

### 2026-05-29 13:56:32
- Добавлено обновление `Project.updated_at` при фактических изменениях графа проекта через агрегированный endpoint graph operations.
- Добавлен CRUD-helper для легкого touch проекта и тесты на обновление timestamp и route-level поведение graph operations.

### 2026-06-02 13:57:10
- В `write_v3` добавлена ранняя валидация `NULL` в не-nullable числовых колонках с понятной ошибкой до попытки вставки в БД.
- Исправлена сборка `column_type_names` для ClickHouse: теперь сохраняется `Nullable(...)` из reflection и корректно обрабатывается `LowCardinality` при формировании nullable-типа.
- Добавлены unit-тесты на раннюю ошибку для числовых `NULL` и на сохранение nullable-типов ClickHouse.

### 2026-05-29 14:18:40
- Реализован модуль `src/modules/db_connection_v1`: добавлены `DVTAccessPolicy`, `DVTConnectionRepository`, `SMBProtocolConnector` и SMB adapter, обновлен `facade` для внешней передачи actor dependency без импортов из `services`.
- Исправлены схемы и маппинг ошибок для `db_connection_v1`, удалена локальная `infra/actor.py`, добавлен unit-тест `tests/unit/src/modules/db_connection_v1/test_db_connection_v1.py` и зафиксирована зависимость `smbprotocol` в `requirements.txt`.

### 2026-06-01 15:47:32
- Добавлен use case `ResolveConnectionClientUseCase` в `src/modules/db_connection_v1/flow/use_cases` с envelope `ResolvedConnectionClient` и builder-экспортами из фасада модуля.
- `GetExistDBConnection` переведен на `db_connection_v1`: нода теперь загружает actor пользователя, получает runtime client через новый use case и отклоняет не-SQL клиенты с сохранением внешнего `ValueError`-контракта.
- Исправлен ownership mapping в `DVTConnectionRepository` для `connections_v1` и обновлены unit-тесты модуля `db_connection_v1` и ноды `GetExistDBConnection`.

### 2026-06-01 17:12:03
- Обновлен `src/modules/file_storage`: модуль переведен на bound-facade контракт с собственными resolved storage DTO и больше не зависит от legacy `db_connection`/`DBConnection`/`ConnectionManager`.
- Переписан S3 list-path flow внутри `file_storage` без использования helper-ов из `db_connection_v0_4`, а FTP/SFTP gateway переведены на готовые runtime-клиенты.
- Обновлены `services/gateway/routes/storage` и их dependency layer: storage-роуты теперь получают параметры подключения через `build_resolve_connection_client_use_case` из `src/modules/db_connection_v1`.
- Добавлены и обновлены unit-тесты для новых storage dependency, factory/gateway wiring и route-контракта; целевой прогон `tests/unit/src/modules/file_storage` и `tests/unit/services/gateway/routes/storage` проходит успешно.

### 2026-06-01 22:40:20
- В миграцию `migrations/versions/0054_add_new_dbconnection_v1_model.py` добавлен перенос данных из legacy-таблицы `db_connections` в новую `connections_v1`.
- Для миграции реализованы разбор legacy `connection_properties`, перенос `kind`/`driver`/`driver_options`, дешифровка старых `fernet$`-секретов и повторное шифрование в поле `secrets_ciphertext` нового формата.

### 2026-06-02 00:19:53
- Добавлена ролевая резолюция владельца для `db_connection_v1` и библиотеки `db-connection`: введен `ConnectionOwnershipResolver`, `POST /check` переведен на actor-aware обработку, а `user_id`/`organization_id` теперь могут вычисляться из actor при create/update/check.
- Обновлены DVT-схемы и репозиторий `db_connection_v1`, добавлен `DVTConnectionOwnershipResolver` с валидацией пары пользователь/организация, расширены unit-тесты в `Visual_transformer` и целевые тесты в `db-connection`.

### 2026-06-02 13:15:21
- Реализован рефактор connection-нод на wrapper-ы вокруг `ConnectionRecord` для SQL/S3/FTP/Kafka.
- Добавлены shared helper-ы `src/node_dsl/connection_runtime.py`, typed-wrapper-ы `src/node_dsl/connection_types.py` и файловый mixin `FileConnectionInputMixin`.
- Обновлены extract/tool/write ноды для ленивого резолва SQL engine и общего построения `FsCtx` для файловых подключений.
- Сохранена совместимость DSL/UI-типов портов, добавлен `IO.FILE_CONNECTION` для файловых consumer-нод и исправлена backend-валидация несовместимых связей через `IO.is_subset()`.
- Обновлены и добавлены unit-тесты на типы портов, pipeline validation и поведение затронутых SQL/file нод.

### 2026-06-02 17:38:00
- В `migrations/env.py` убраны прямые импорты custom-типов `db_connection.compat.sa_types.PydanticType`, `src.models.sa_types.PydanticType` и `src.models.sa_types.JSONBCompat`.
- Логика `render_item` и `compare_types` переведена на структурную проверку JSON-backed `TypeDecorator` через `impl`, чтобы сохранить совместимость Alembic autogenerate без жесткой привязки к конкретным классам.

### 2026-06-02 18:45:17
- `services/gateway/deps/db_connection.py` переведен с legacy `src.models.DBConnection` и `src.crud.db_connection` на `src.modules.db_connection_v1`: dependency теперь получает `ConnectionRecord` через `build_connection_service(...).get(..., actor=user)` и маппит ошибки доступа/отсутствия в `DBConnectionNotFoundException` для сохранения внешнего поведения.
- `services/gateway/routes/utils/sql_query_to_metadata.py` и `services/gateway/routes/utils/csv.py` адаптированы под `ConnectionRecord`: legacy `connection_properties`/`ConnectionManager` заменены на `SqlConnectionRecord` + `resolve_sql_engine` и `FileConnectionRecord` + `resolve_file_fs_context`.
- Добавлены unit-тесты для нового gateway dependency и обновлены тесты SQL metadata route под v1-поток получения соединения.

### 2026-06-03 14:53:21
- Обновлены unit-тесты `services/gateway/routes/project/test_copy.py`: тестовые данные переведены на async-фикстуры и вызовы `copy_project` приведены к актуальной сигнатуре.
- Переписан тест `services/gateway/routes/project/test_public_task.py` на проверку dependency через `Annotated` metadata.
- Актуализированы тесты `services/gateway/routes/public/db_connection/test_db_connection.py` под новый `db_connection_v1` HTTP-контракт с маршрутами `/check` и payload-полями `kind/properties/secrets`, с моками `public_db_connections_ext.runtime.service`.
- Обновлен unit-тест `src/modules/sql_code_metadata/test_use_cases.py` под текущий контракт `SQLValidationPolicy`.

### 2026-06-03 16:07:00
- Добавлен `src/db_connection_compat.py` с fallback-импортом `ConnectionRecord` и безопасной инициализацией legacy `fernet`-конфига для разных версий пакета `db_connection`.
- Обновлены `services/gateway`, `services/task_worker` и `services/task_benchmarking`: прямые импорты `db_connection.compat.extension_config` заменены на общий compatibility helper, а `gateway` на Windows теперь принудительно использует `WindowsSelectorEventLoopPolicy`.
- Расширена совместимость `src/node_dsl/connection_runtime.py` с legacy file/S3/FTP connection-объектами без `.record`, чтобы integration pipeline-тесты не падали на старых фикстурах.
- Переписаны integration-тесты `tests/integration/services/gateway/routes/test_db_connections.py` и `tests/integration/services/gateway/routes/public/db_connection/test_db_connection.py` под актуальный `db_connection_v1` HTTP-контракт.
- В `tests/integration/fixtures/app.py` добавлена подмена `db_connection_v1` runtime на общую тестовую `Session`, чтобы in-process gateway integration-тесты использовали тот же тестовый БД-контекст, что и остальной suite.

### 2026-06-03 23:44:27
- Обновлены интеграционные фикстуры подключений в `tests/integration/fixtures/db_connections.py`.
- Контейнерные подключения (`postgres`, `clickhouse`, `mysql`, `mongodb`, `mssql`, `s3`, `oracle`) переведены на создание через `db_connection_v1` с совместимым адаптером для существующих тестов.
- `custom_db_connection` оставлен на старом пути создания, так как тип `custom` отсутствует в реестре `db_connection_v1`.

### 2026-06-03 23:55:57
- Переписаны интеграционные фикстуры подключений на `ConnectionRecord` в `tests/integration/fixtures/db_connections.py`.
- Удалены импорты из `db_connection.compat` и `src.models.DBConnection`; контейнерные подключения теперь создаются через `db_connection_v1`, а `custom_db_connection` возвращает `ConnectionRecord` без legacy-модели.
- Обновлены `tests/integration/fixtures/db_connection_clients.py` и публичные интеграционные тесты db-connections под новый контракт `properties`/`secrets`.

### 2026-06-04 10:42:35
- Обновлены integration-тесты, зависящие от фикстур `tests/integration/fixtures/db_connection_clients.py`.
- В `tests/integration/conftest.py` удалены импорты устаревших legacy-фикстур и оставлены только актуальные `*_test_engine` и `s3_test_client`.
- В read-v3 integration-тестах и матрице `ALL_SQL_DB_ENGINE_FIXTURES` старые имена `mysql_engine` и `mssql_engine` заменены на `mysql_test_engine` и `mssql_test_engine`, обновлена логика skip для MSSQL.

### 2026-06-04 11:04:01
- Исправлены async/db-фикстуры integration-тестов для совместимости scope и видимости данных в транзакциях.
- В `tests/integration/fixtures/db.py` async-фикстуры переведены на `pytest_asyncio.fixture` с совместимым `loop_scope`.
- В `tests/integration/fixtures/db_connections.py` `connection_service` переведен на function scope и использует async-адаптер поверх `test_db_session`, чтобы ownership resolver видел тестовых пользователей и организации.
- В `tests/integration/fixtures/db_connection_clients.py` убрана лишняя обертка `SqlConnectionRecord`/`FileConnectionRecord`, вызывавшая двойное оборачивание новых `ConnectionRecord`.
- После правок целевые integration-тесты по read_v3 и db connection fixtures успешно проходят.

### 2026-06-04 12:25:31
- Исправлены падения integration-тестов cache+redis для `ReadQueryFromDBV3` и `ReadTableFromDBV3`.
- В `tests/integration/src/nodes/extract/read_db_v3_matrix_helpers.py` добавлена indirect-фикстура `resolved_sql_test_engine`, которая резолвит parametrized engine fixture до входа в async test body.
- В `test_read_query_from_db_v3_cache_redis.py` и `test_read_table_from_db_v3_cache_redis.py` убран вызов `request.getfixturevalue(engine_fixture)` из coroutine-тела теста и включена indirect-параметризация по `resolved_sql_test_engine`.
- Это устранило ошибку `RuntimeError: Cannot run the event loop while another loop is running` для всех 10 параметризаций cache integration-тестов.

### 2026-06-04 14:09:02
- В модуле `db_connection` введен собственный lookup-port для проверки владельца подключения и вынесен reusable wiring для runtime/gateway сценариев.
- Удалена прямая зависимость gateway и connection-node'ов от `SQLAlchemyUserRepository`.
- Исправлена обработка отсутствующего пользователя: теперь missing user снова преобразуется во внутреннюю validation error модуля `db_connection`, а node-ы сохраняют прежний user-facing сценарий ошибки подключения.
- Обновлены unit/integration тесты для нового порта и сценария missing user.

### 2026-06-04 17:14:27
- Добавлена нормализация record-like объектов подключения перед runtime-валидацией через `ValidationService`.
- Исправлены пути `src/node_dsl/connection_runtime.py` и `src/modules/db_connection/flow/use_cases/resolve_connection_client.py`, чтобы отсутствующие `labels`, `metadata` и `extra` заполнялись значениями по умолчанию.
- Обновлены и добавлены unit-тесты для совместимости с legacy-объектами подключения и для happy path на реальном `ConnectionRecord`.

### 2026-06-05 12:07:46
- Исправлен `SMBProtocolClient`, чтобы все операции `smbclient` явно использовали настроенный порт подключения, а не значение по умолчанию `445`.
- Обновлены unit-тесты `tests/unit/src/modules/db_connection_v1/test_db_connection_v1.py` под актуальную SMB-схему с полями `host` и `port`.
- Добавлена проверка, что `listdir` проксирует `port` в вызов `smbclient`.

### 2026-06-05 12:49:30
- Добавлена нода `GetExistSMBConnection` и SMB-типизация в `node_dsl` для отдельного семейства file-connections с `type="smbprotocol"`.
- Расширен `resolve_file_fs_context()` и `FsCtx` для SMB через `fsspec`, а `LoadCSV`, `LoadParquet`, `LoadExcel`, `SaveCSV`, `SaveParquet`, `SaveExcel` получили совместимость с `smb://` путями.
- Добавлены отдельные SMB metadata models и backend loader `core.metadata.smb_metadata`, а также покрытие unit-тестами для DSL, pipeline validation, connection node, metadata loader и file nodes.

### 2026-06-05 14:57:40
- Реализован `SMBFileStorageGateway` в модуле `file_storage` без межконтекстных импортов в `db_connection`: добавлены операции листинга, создания каталогов, rename/move, удаления, upload/download и ошибки для unsupported presign.
- Расширены экспорты и тип `StorageBackendKind` для SMB, а также добавлены unit-тесты для SMB gateway, фабрики storage gateway и маппинга `smbprotocol` в storage deps.

### 2026-06-05 16:28:32
- Для тестового SMB-окружения добавлена инициализация прав на volume `samba_test_data` через отдельный сервис `samba_test_db_init` в `docker/docker-compose.tests.yaml`, а `samba_test_db` теперь стартует после успешного применения `chown/chmod` к `/samba/public`.
- В `SMBFileStorageGateway` исправлена логика `_ensure_dir`: ошибки доступа при `stat` больше не трактуются как отсутствие директории, добавлено unit-покрытие сценария `access denied` без ложного вызова `mkdir`.

### 2026-06-05 16:49:12
- В `SMBFileStorageGateway.list_nodes` устранен лишний повторный `stat` для элементов SMB-каталога: маппинг файлов и папок теперь использует metadata из `smbclient.scandir()` (`smb_info`) без дополнительных сетевых вызовов, что убирает сбои вида `STATUS_BAD_NETWORK_NAME` на тестовом Samba-таргете.
- Обновлены unit-тесты SMB gateway так, чтобы листинг падал при случайном возврате к `DirEntry.stat()`, сохраняя защиту от регрессии.

### 2026-06-05 17:56:20
- Добавлена миграция `0055_move_s3_prefix_to_file_node_path`, которая для file-нод (`LoadCSV`, `LoadExcel`, `LoadParquet`, `SaveCSV`, `SaveExcel`, `SaveParquet`) переносит S3 `prefix` из `connections_v1.properties_json` в `input_values.path` по связям с `GetExistS3Connection`.
- Добавлены unit-тесты на перенос `prefix` в `path`, идемпотентность, обработку expression-path и защиту от неоднозначных `connection`-связей.

### 2026-06-05 18:56:38
- Для `FileConnectionInputMixin` добавлен новый schema-input `connection_overrides` с type-specific override-моделями для S3, FTP и SFTP.
- В `connection_runtime` добавлена поддержка переопределения `bucket`, `prefix` и `initial_directory` без изменения исходного connection record, включая семантику явного сброса через пустую строку.
- Добавлены unit-тесты на schema `oneOf`, валидацию несовместимых override-веток и построение итоговых путей для S3/FTP/SFTP.

### 2026-06-08 18:26:14
- Добавлена поддержка MSSQL типов `uniqueidentifier`, `binary` и `varbinary` в `core/db/read_v3` и `core/db/write_v3`.
- Для `read_v3` реализован MSSQL-specific string cast: `CAST(... AS NVARCHAR(MAX))` для `uniqueidentifier` и `CONVERT(VARCHAR(MAX), ..., 2)` для бинарных колонок, включая корректную обработку metadata и query introspection.
- Для `write_v3` добавлен pre-coercion строковых UUID и hex-строк в значения, совместимые с MSSQL bind-параметрами.
- Расширены unit-тесты и metadata-покрытие для новых MSSQL сценариев.

### 2026-06-08 22:20:28
- Переработан GitLab CI failure analysis для OpenCode/OpenRouter: разбор падений вынесен из `after_script` упавших job в отдельные companion-job стадии `failure_analysis`, а исходные job теперь только отправляют базовое уведомление и сохраняют status snapshot/seed bundle в artifacts.
- Failure-analysis переведен на Markdown как первичный формат с последующей конвертацией через `scripts/.ci/markdown_to_bbcode.py`, добавлен раннер `scripts/.ci/run_failure_analysis.py`, а также улучшена обработка ошибок OpenRouter с понятными сообщениями для Bitrix24, включая сценарий нехватки кредитов.
- Добавлены unit-тесты для нового flow: metadata bundle, Markdown->BB-code, публикация history в формате `markdown` и разбор структурированных ошибок OpenRouter.

### 2026-06-15 16:43:20
- Добавлен скрипт `scripts/analysis/render_gitlab_ci_pipeline.py` для разбора `.gitlab-ci.yml` с локальными include, `extends` и child pipeline trigger-ами с последующей генерацией PNG/JPEG-схемы пайплайна с тегами раннеров на каждой job.
- Добавлены unit-тесты `tests/unit/scripts/test_render_gitlab_ci_pipeline.py` на synthetic-конфиги и на разбор актуального GitLab CI-конфига репозитория.

### 2026-06-15 17:57:40
- Обновлены e2e-фикстуры контейнеров: при `DVT_E2E_BUILD=true` перед тестами запускается сборка prod-образов через `scripts/docker/build_prod.py`, а при `false` выполняется ранний `docker pull` образов из container registry по тегу `DVT_E2E_DVT_VERSION`.
- Исправлен резолв имён образов для registry/prod-режима и smoke-тест `tests/e2e/test_containers_smoke.py`, чтобы он проверял ожидаемые образы в обоих сценариях.
- Фикстура `settings` переведена на `session` scope, чтобы убрать конфликт областей видимости с session-level e2e контейнерами.

### 2026-06-16 16:28:41
- Добавлен пакет `src/clients/gateway_sdk` с async/sync Python SDK для Gateway на базе `httpx`, включая resource-style namespaces, обработку auth, HTTP-ошибок и бинарных ответов.
- Добавлен генератор `scripts/misc/generate_gateway_sdk.py`, который собирает модели, operation metadata и resource-классы из OpenAPI c fallback на локальный `services.gateway.main.app.openapi()`.
- Добавлены README и тесты для SDK: unit-тесты на auth, public token flow, raw body `store` и binary download, а также интеграционные тесты для `db_connections` и public-ресурсов с корректным skip при недоступном Docker.

### 2026-06-16 17:24:52
- В `tests/e2e` переведены обращения к Gateway API с прямого `httpx`/`requests` на `src/clients/gateway_sdk`.
- Обновлены фикстуры setup/auth, создания пользователей и проектов, работы с DB connections и запуска pipeline через graph/task SDK-методы.

### 2026-06-16 17:50:40
- Переведены функции `_submit_setup_step` и `_ensure_gateway_setup` в `tests/e2e/fixtures/gateway.py` на асинхронный `DVTClient`.
- Фикстура `gateway_auth_headers` переведена на `pytest_asyncio` и асинхронный логин через `DVTClient`, а `gateway_sdk_client` теперь зависит от нее для гарантированного завершения gateway setup перед e2e-вызовами.

### 2026-06-16 18:31:01
- Обновлен генератор `gateway_sdk`: вложенные async/sync ресурсы теперь строятся по path-дереву Gateway, а базовые классы инициализируют дочерние ресурсы симметрично через type hints.
- Исправлены клиенты `DVTClient` и `DVTSyncClient`, обновлены manual auth resources, regenerated файлы `generated/*`, README и тесты под новую вложенную поверхность вызовов (`storage.download.file`, `projects.tasks.new`, `projects.graph_ops` и др.).

### 2026-06-16 19:01:55
- Исправлены E2E-фикстуры авторизации Gateway/WebSocket.
- `gateway_sdk_client` теперь выполняет setup и логин в собственной сессии, а `project_pipeline_run_via_ws` использует актуальные auth cookies из того же клиента при подключении к WebSocket, чтобы избежать инвалидирования токена из-за второго логина.

### 2026-06-16 19:06:08
- Устранена регрессия в E2E-фикстуре `gateway_sdk_client`.
- Клиент Gateway для E2E теперь проходит `/setup/*` без заранее заданных credentials, а логин и сохранение username/password в transport выполняются только после завершения setup, чтобы исключить преждевременный `POST /api/auth/sign-in` и ошибку 403 до инициализации Gateway.

### 2026-06-17 13:57:45
- Добавлен асинхронный CI-контур автоматического AI-обновления `src/clients/gateway_sdk` после `deploy_dev`: новый child pipeline готовит diff OpenAPI и контекст изменений Gateway, запускает OpenCode-агента с ограничением на правки только внутри SDK, валидирует результат, создает ветку `dev-gateway-sdk-*`, MR и отправляет уведомление в Bitrix24.
- Добавлены скрипты подготовки контекста и оркестрации обновления SDK, helper для канонического SHA-256 хэша `openapi.json`, новые OpenCode-конфиги/агент, а также расширен GitLab API helper для поиска веток и создания MR через bot token.
- Обновлен `run_opencode.py` для поддержки runtime permission overrides, добавлены unit-тесты для нового контура и для расширенной GitLab/OpenCode логики.

### 2026-06-19 12:21:46
- Подготовлен аналитический отчет `tmp/node_error_interception_report.md` по внедрению перехвата ошибок нод.
- В отчете описаны ограничения текущей архитектуры, валидация идеи с `signal`-веткой ошибки, альтернативы и высокоуровневый план реализации.

### 2026-06-19 12:34:17
- Обновлен отчет `tmp/node_error_interception_report.md` после уточнений по требованиям.
- Добавлена оценка стоимости статуса `PARTIAL_SUCCESS`, зафиксировано решение для первой итерации оставлять task-level статус `ERROR`, а также уточнены ограничения: перехватываются только runtime exception и вниз по графу передается только `error_text`.

### 2026-06-19 14:18:56
- Реализован перехват runtime-ошибок нод через новый базовый выход `signal_error` с сохранением task-level статуса `ERROR` и отложенной отправкой task-level ошибки до завершения выполнения пайплайна.
- Добавлена базовая runtime-переменная `__dvt_error_text`, материализация error-path в `PipelineProcessor`, совместимость metadata-cache со старыми entry без signal-выходов и защита `graph/builders` от выбора `signal_error` как terminal output.
- В Gateway добавлен read-only роут `/nodes/base-variable-definitions`, обновлены backend OpenAPI/SDK-модели и unit-тесты для нового error-branch контракта.

### 2026-06-22 14:08:04
- В файле `docker/ftp/ftp-test-db-entrypoint.sh` исправлены окончания строк на `LF`, чтобы Linux-контейнер корректно исполнял entrypoint-скрипт без ошибки `No such file or directory`.

### 2026-06-22 14:57:51
- Исправлена конфигурация child pipeline `dev-postdeploy-integration`: добавлен include файла `.ci/gitlab/00-rules.yml`.
- Это восстанавливает разрешение `!reference [.rules_failure_analysis_on_failure, rules]` и устраняет ошибку создания pipeline в GitLab CI.

### 2026-06-22 15:25:20
- В `services/task_worker/tasks/worker_tasks.py` восстановлен вызов `ensure_log_sinks_for_task_process()` в `handle_task()`, чтобы `LogEvent` снова инициализировал доставку логов в WebSocket для UI.
- В `tests/unit/services/task_worker/tasks/test_worker_tasks.py` добавлена проверка, что при обработке задачи инициализация логовых sink'ов действительно вызывается.

### 2026-06-23 12:45:51
- В узле `LoadExcel` исправлено чтение Excel по FTP: для каждого чтения теперь создается отдельный `fsspec`-filesystem, чтобы Dask-партиции не делили один FTP control connection и не падали с ошибкой `200 Switching to Binary mode`.
- Добавлен unit-тест, который проверяет создание нового FTP filesystem для каждого чтения Excel-файла.

### 2026-06-23 16:51:38
- Исправлена генерация хэша Gateway OpenAPI для CI-джоба `gateway_sdk_update_worker`: добавлена поддержка списка URL через `;` с последовательным fallback на доступный адрес.
- Обновлен `prepare_gateway_sdk_context`, чтобы в экспорт и метаданные попадал фактически использованный OpenAPI URL.
- Добавлены unit-тесты на многозначный `DVT_DEV_PUBLIC_URL` и сценарий падения первого адреса с успешным чтением `openapi.json` по следующему URL.

### 2026-06-25 14:39:56
- Добавлен автономный диагностический скрипт `tmp/ftp_excel_probe.py` для проверки сценария FTP -> `pd.read_excel` без зависимостей на код репозитория.
- Добавлены `tmp/ftp_excel_probe.README.md` и `tmp/ftp_excel_probe.sample.json` с инструкцией по настройке, установке зависимостей и запуску проверки.
- В отчет скрипта включены замеры сырого FTP-потока, локальной копии файла, Dask-пайплайна и статистика `read`/`seek`/`tell` для анализа timeout-проблем при чтении Excel.

### 2026-06-25 16:29:46
- Для ноды `LoadExcel` добавлено чтение Excel по FTP через схему `download-to-temp-then-read` без изменения контракта ноды.
- Сохранен рабочий таймаут `read_timeout_sec` на всю операцию чтения одного файла.
- Добавлены unit-тесты на fresh FTP filesystem для каждого чтения, чтение metadata через временный файл и очистку временных файлов при успехе и ошибке.

### 2026-06-25 18:22:34
- Исправлена запись в ClickHouse для `write_v3` и `write_v4` в staging-сценариях: для режимов `truncate` и `upsert` отключен `async_insert`, чтобы исключить гонку между асинхронной вставкой и удалением staging-таблицы.
- Исправлен lifecycle SQLAlchemy `Engine` в write-нодах V3/V4: node-owned подключения теперь гарантированно закрываются через `dispose()`, а инвалидация meta-cache повторно использует уже открытый engine без создания лишних соединений.
- Добавлены unit-регрессии на переключение режима вставки в ClickHouse executor и на корректное освобождение node-owned engine.

### 2026-06-25 19:11:26
- В узле `LoadExcel` изменена сборка Dask-задач для FTP-чтения: добавлена явная зависимость между партициями, чтобы сохранить последовательный порядок скачивания файлов и исключить перестановку чтений планировщиком.
- Проверен файл тестов `tests/unit/src/nodes/extract/test_file_nodes_smb.py`: все тесты проходят.

### 2026-06-25 19:15:07
- Для `LoadExcel` отменена искусственная сериализация FTP-чтений в Dask: порядок выполнения задач не считается контрактом узла.
- Переписан тест `test_load_excel_process_uses_fresh_ftp_fs_for_each_read`: теперь он проверяет использование нового FTP filesystem на каждое чтение и состав прочитанных файлов без зависимости от порядка исполнения задач.

### 2026-07-02 21:20:19
- Изменены правила запуска `e2e_tests_failure_analysis` и `e2e_playwright_failure_analysis`: анализ ошибок теперь запускается только при падении соответствующих E2E job, а не всегда.
- Это предотвращает удержание stage `failure_analysis` в активном состоянии после успешных E2E проверок.

### 2026-07-02 21:22:08
- Обновлена job `e2e_tests` в GitLab CI: для release/rc тегов сохранены зависимости от `publish_images` и `notify_preprod_update`, а для остальных ref добавлен ручной запуск без `needs`.
- Это позволяет запускать `e2e_tests` вручную из любой ветки без создания тега и без ожидания release job.

### 2026-07-03 13:19:13
- Обновлен Python SDK Gateway в `src/clients/gateway_sdk` под актуальный OpenAPI.
- Добавлена поддержка MSSQL подключений через named instance в сгенерированных моделях SDK.
- Обновлены `openapi.hash` и снимок `openapi.snapshot.json`.

### 2026-07-03 14:01:08
- Улучшено логирование GitLab CI job для обновления Gateway SDK.
- Добавлены секции GitLab, безопасный вывод выполняемых команд, контекст job и подробная диагностика при ошибке.

### 2026-07-07 15:18:21
- Добавлены bootstrap-скрипты в `tmp/e2e_bootstrap` для создания и заполнения одинаковых SQL-таблиц `e2e_src.customers` и `e2e_src.orders` во всех SQL-подключениях из `playwright.env`.
- Исправлен экспорт `tmp/e2e_bootstrap/settings/__init__.py`, чтобы `E2EBootstrapSettings` импортировался без преждевременного создания настроек.

### 2026-07-08 10:03:58
- Нода `DataFrameDropNA` заменена на `DataFrameFillNA` с заполнением NA/null значений по словарю колонок.
- Обновлены экспорт transform-нод, локализации и unit-тесты для новой ноды.

### 2026-07-08 10:09:21
- Для `DataFrameFillNA` значения `fill_values` типизированы через `Literal` с поддерживаемыми функциями заполнения NA.
- Реализовано заполнение по функциям `mean`, `median`, `mode`, `min`, `max`, `ffill`, `bfill` и обновлены unit-тесты.

### 2026-07-08 10:56:38
- Исправлена нормализация пустых строк для optional-полей `AppConfig`, объявленных через синтаксис `T | None`.
- Проверен unit-тест `tests/unit/src/models/test_app_config.py`.

### 2026-07-09 16:47:22
- Добавлена гарантированная очистка временных артефактов `/tmp/*.partd` после выполнения задач `task_worker.handle_task`.
- Обновлены unit-тесты `services/task_worker`, проверяющие удаление partd-файлов и запуск очистки при успешном, неуспешном и аварийном выполнении задачи.

### 2026-07-14 14:42:26
- Реализовано автоматическое заполнение `output_variables` в `ExecuteSQL` для SQL-запросов, возвращающих ровно одну строку.
- Добавлены unit-тесты для SELECT, RETURNING и SQL Server OUTPUT, а также integration-тест для `INSERT ... OUTPUT INSERTED` в SQL Server.

### 2026-07-16 13:31:48
- Исправлено нарушение границ DDD-lite в модуле `src/modules/db_connection`: `flow` больше не зависит от SQLAlchemy при создании пользовательского репозитория.
- Добавлен infra-адаптер `SessionScopedUserRepository`, который инкапсулирует работу с session factory и маппинг пользователя в доменную модель `ExistingUser`.
- Обновлены связанные тестовые фикстуры и проверки ownership resolver под новый доменный контракт.

### 2026-07-17 14:31:20
- Исправлено восстановление `driver_options` при маппинге сохраненных подключений в `DVTConnectionRepository`.
- Добавлен unit-тест, проверяющий сохранение параметров драйвера MSSQL после create/get/list.

### 2026-07-29 17:00:05
- Реализован bounded context `src/modules/app_settings` как замена устаревшего `src/models/app_config.py`.
- Секретные настройки перенесены в общую таблицу настроек с Fernet-шифрованием через `config.SECURITY.FERNET_KEY`.
- Обновлены backend-вызовы, Gateway API, setup-flow, миграция, Python Gateway SDK и тесты под новый контракт настроек.

### 2026-07-29 19:47:38
- Доработан модуль `src/modules/app_settings` по замечаниям к архитектуре.
- Добавлена поддержка иерархии `Namespace -> Group -> Setting`, concrete registry перенесен в `public.DVTApplicationSettings`.
- Pydantic-схемы настроек теперь генерируются из DSL, Gateway API переименован в `/app-settings`, а project-specific use case заменен на общий `EnsureSetting`.

### 2026-07-29 20:33:14
- Добавлен endpoint `GET /app-settings/definitions` для получения определений настроек приложения.
- Удалены gateway endpoint-ы `/app-settings/fields/required` и `/app-settings/fields/required/unfilled`; определения теперь сериализуются через mapper и schema слоя `infra` модуля `app_settings`.

### 2026-07-29 23:33:33
- Обновлена схема определений настроек приложения: поле `value_type` теперь возвращает JSON Schema для сложных аннотаций, включая Pydantic-модели, enum, Literal и Union.
- `OOMGuardConfig` переведен на Pydantic-модель с сохранением правил валидации OOM guard.

### 2026-07-30 11:59:56
- Настройки приложения переведены на типизированные frozen dataclass-модели с автоматическим преобразованием через `SettingsModel` и PEP 681.
- Конкретный тип `DVTAppSettings` протянут через реестр, провайдер, use case, кэш и публичную функцию `get_app_settings` без дублирования описаний настроек.
- Сохранена совместимость с декларативным API `Setting`/`SettingsNamespace`, обновлены типы потребителей и unit-тесты.

### 2026-07-30 13:41:31
- Добавлена поддержка настраиваемой точности datetime для `read_v3`.
- Настройки выполнения теперь передаются через `ExecutionSettings` из Task Worker в ноды чтения.

### 2026-07-30 14:24:58
- Исправлена изоляция unit-тестов OOM guard оркестратора: сценарии явно подменяют настройки приложения для режимов давления памяти хоста, процентного и абсолютного порога воркера.

### 2026-07-31 11:46:08
- Проведен архитектурный анализ `src/node_dsl` и `src/pipeline` с учетом DDD-lite правил проекта.
- Добавлен отчет `tmp/node_dsl_pipeline_ddd_refactoring_report.md` с рекомендуемыми границами модулей, контрактами, планом миграции и матрицей сохранения существующих бизнес-функций.

### 2026-07-31 12:52:06
- Дополнен архитектурный отчет `tmp/node_dsl_pipeline_ddd_refactoring_report.md`.
- Добавлены рекомендации по устранению зависимости от Dask через backend-контракты и артефакты, а также схема двустороннего преобразования `Engine Graph` и DVT Pipeline через канонический Execution IR и provenance manifest.

### 2026-07-31 14:05:37
- Добавлен Markdown-отчёт в `tmp/` с полным аудитом импортов `src.node_dsl` внутри `src.pipeline`, оценкой принадлежности каждой сущности и безопасной последовательностью возможного переноса.

### 2026-08-03 12:09:48
- Добавлены постоянные поля `dirty_node_ids` и `graph_revision` проекта с миграцией БД и снимком состояния в задачах.
- Реализовано восстановление полного снимка DataFrame и метаданных из кэша до первой измененной ноды для FULL- и METADATA-запусков с безопасным fallback при неполном кэше.
- Добавлена revision-safe очистка dirty-состояния после успешного полного запуска всего пайплайна и unit-тесты для новых сценариев.

### 2026-08-03 13:41:18
- Исправлена очистка dirty-состояния графа после успешного FULL-запуска с целевыми нодами: task worker теперь снимает отметки только с обработанных `changed_node_ids`, сохраняя dirty-ноды вне частично выполненного подграфа. Добавлены unit-тесты для целевых запусков и частичной revision-safe очистки.

### 2026-08-03 14:40:05
- Добавлена диагностическая задача `tmp/analyze_pipeline_cache_restore_failure.md` для установления точной причины отсутствия восстановления DataFrame-нод из кэша без внесения исправлений.

### 2026-08-03 15:23:08
- Реализована идемпотентная финализация успешных задач в Task Worker: при повторном переходе `SUCCESS -> SUCCESS` подтверждается сохранённый статус и продолжается revision-safe очистка `dirty_node_ids`. Добавлены unit-тесты, запрещающие очистку для `ERROR`, `CANCELLED` и отсутствующей задачи.

### 2026-08-03 19:42:04
- Исправлена нестабильная загрузка FTP-файлов в нодах `LoadCSV`, `LoadExcel`, `LoadJSON` и `LoadParquet`: добавлено скачивание через `FTPFileSystem.get_file()` на новой сессии с временным локальным файлом.
- Добавлены unit-тесты FTP-чтения и сохранён диагностический отчёт `tmp/ftp_load_nodes_root_cause_report.md`.

### 2026-08-04 11:51:46
- Исправлена подсистема загрузки расширений: устранены повторные и реентерабельные импорты, добавлены единый атомарный runtime refresh, изоляция ошибок расширений и полное исключение отключённых расширений.
- Усилены валидация путей, пространств имён, совместимости и конфликтов backend-пакетов, а также безопасная очередь отложенного удаления.
- Обновлены запуск Gateway и Task Worker, реестры Node DSL, документация и регрессионные тесты расширений.

### 2026-08-04 12:28:40
- Расширена поддержка типов Microsoft SQL Server в `core/db/read_v3`: добавлены корректные преобразования BIT, MONEY, SMALLMONEY, TIME, IMAGE, ROWVERSION/TIMESTAMP, XML, SQL_VARIANT, HIERARCHYID, GEOMETRY, GEOGRAPHY и VECTOR, а также fallback метаданных для типов, не распознаваемых SQLAlchemy.
- Добавлены unit- и integration-тесты чтения расширенного набора типов через реальный SQL Server.

### 2026-08-04 12:58:58
- Добавлен policy/registry разрешённых атрибутов для безопасного доступа к системной переменной `input_variables.__dvt_error_text` без ослабления Jinja sandbox.
- Улучшена обработка `SecurityError`: ошибки выражений преобразуются в диагностируемые `NodeInputError` без префикса `Unexpected error`.
- Добавлены регрессионные тесты evaluator, Gateway-конфигурации и обработки error-ветки пайплайна.

### 2026-08-04 13:25:50
- Исправлена изоляция реестров в unit-тесте перестроения встроенных нод: исходное состояние теперь восстанавливается после проверки.
- Обновлен тест metadata variable prepass для monkeypatch фактически зарегистрированного класса `ReadQueryFromDBV3`.

### 2026-08-04 14:32:01
- Исправлена загрузка встроенных нод: registry теперь использует канонические модули `src.nodes.*` и сохраняет идентичность классов при перестройке, а extension-модули продолжают перезагружаться изолированно.
- Добавлен регрессионный тест стабильности идентичности встроенной ноды.

### 2026-08-04 15:38:35
- Исправлен запуск failure analysis для `integration_tests` и `integration_tests_dev`: DAG-зависимости `needs: optional` заменены на загрузку артефактов через `dependencies`, а `when: on_failure` унифицирован в общем шаблоне.
- Исключена отправка merge-уведомления в tag pipeline и добавлено отдельное уведомление Bitrix24 о создании тега с автором, коммитом и ссылкой на pipeline.
- Добавлены unit-тесты CI-правил и шаблона сообщения о теге.

### 2026-08-05 11:45:32
- Обновлено именование колонок в ноде `DataFramePivot`: значения pivot-колонки сохраняются без префикса, а префиксы и числовые суффиксы добавляются только при коллизиях. Добавлены unit-тесты для одиночных и нескольких value-колонок, выборочного префикса и конфликтующих имён.

### 2026-08-05 12:27:59
- Добавлена передача `input_variables` из ноды `ExecuteProject` в дочерний проект как runtime-переопределений.
- Добавлены настраиваемые политики обработки unresolved- и system-переменных, а также целевые unit- и integration-тесты.

### 2026-08-05 13:15:05
- Добавлены общие неизменяемые представления для входных и проектных переменных нод на базе `ImmutableVariables`.
- Узлы `ExecutePython` и `DataFrameExecCode` переведены на единый контракт с раздельными `ImmutableInputVariables` и `ImmutableProjectVariables`.
- Добавлены unit-тесты точечного и словарного доступа, неизменяемости и разделения пространств переменных.

### 2026-08-05 15:09:41
- Обновлён unit-тест узла `ExecuteProject`: ожидаемый вызов постановки дочерней задачи дополнен аргументами передачи переменных и политик их обработки.

### 2026-08-05 20:15:23
- В общие dev- и prod-builder Docker-образы добавлен корневой `pyproject.toml`, чтобы Python-сервисы получали корректную версию DVT внутри контейнеров.

### 2026-08-05 20:18:40
- Удалено дублирующее копирование корневого `pyproject.toml` из dev- и prod-Dockerfile сервиса Gateway; файл теперь поступает через общие builder-образы.

### 2026-08-06 13:08:42
- Добавлен DDD-lite модуль `src/modules/data_catalog` с доменными типами `TableSchema` и `ColumnSchema`, use case `BuildSchema` и инфраструктурным преобразованием Dask DataFrame в схему таблицы.
- Реализована нода `Convert To Schema`, добавлен тип порта `IO.TABLE_SCHEMA`, регистрация ноды и поддержка сериализации схемы.
- Добавлены unit-тесты доменных инвариантов, строгого маппинга, сортировки колонок, работы ноды, разрешения IO-типа и dump/load.

### 2026-08-06 14:45:40
- Добавлена проверка целостности графа Alembic-миграций и автоматическая синхронизация его единственной головной ревизии с файлом `RELEASE` через pre-commit и pre-push.
- Добавлено ожидание требуемой ревизии базы данных перед запуском orchestrator, task worker и project scheduler, включая настройку таймаута, Docker-конфигурацию и unit-тесты.

### 2026-08-06 14:50:31
- Добавлена временная no-op Alembic-миграция `0058` с пяти­минутной задержкой для проверки блокировки запуска сервисов до завершения миграций.
- Файл `RELEASE` синхронизирован с ревизией `0058`.

### 2026-08-06 18:41:57
- Добавлена автоматическая синхронизация `ALEMBIC_REVISION` в файле `RELEASE` после успешного создания Alembic-миграции через post-write hook.
- Генерация последовательного ID миграции изменена с подсчёта файлов на максимальный существующий числовой ID плюс один; добавлены проверки CLI-режима hook и алгоритма ID.

### 2026-08-06 19:24:38
- Возвращён обязательный четырёхзначный числовой формат Alembic revision ID для обычного `alembic revision` и `--autogenerate` без необходимости подключения к проектной БД при создании пустой миграции.
- Тестовая hash-ревизия `88476835abf3` перенумерована в `0058`, а `RELEASE` синхронизирован с `0058`; валидаторы графа и runtime metadata теперь отклоняют ID не в формате `NNNN`.

### 2026-08-07 10:30:34
- Исправлен интеграционный тест Celery task worker: тестовая база данных после `SQLModel.metadata.create_all()` помечается текущей Alembic-ревизией, чтобы воркер не ожидал внешние миграции.
- Добавлена регистрация модели `app_setting_values` в тестовой metadata.

### 2026-08-07 11:27:05
- Исправлена инициализация общей DVT-базы в интеграционных тестах production-контейнеров: перед запуском Orchestrator схема создаётся, помечается текущей Alembic-ревизией и ожидает готовности PostgreSQL.
- Добавлена явная регистрация таблицы `app_setting_values` в тестовой metadata, чтобы изолированный запуск Gateway не зависел от порядка импорта тестовых модулей.

### 2026-08-10 12:23:00
- Локализован автоматический пересчет метаданных текущим измененным подграфом вместо накопленного списка dirty-нод.
- Добавлена публикация метаданных при раннем восстановлении из кеша и продолжение независимых веток после runtime-ошибки в режиме `metadata_only`.
- Добавлены unit-тесты для scoped metadata-задач, cache hit и изоляции ошибок по веткам.

### 2026-08-10 13:05:01
- Для ноды `ConvertToSchema` добавлен расчет `TableSchemaMetadata` с полным переносом атрибутов колонок.
- Добавлены unit-тесты для полной схемы и metadata-only режима.

### 2026-08-10 17:14:00
- В Project Scheduler добавлены устойчивые к перезапуску цепочки повторных запусков с fixed/exponential backoff, защитой от пересекающихся cron-запусков и восстановлением зависшего старта.
- Расширены модели, API и история scheduler-запусков настройками retry-policy и данными попыток; добавлена миграция `0058` и unit/integration-тесты.

### 2026-08-11 16:07:29
- Исправлено преобразование отраженных типов ClickHouse в core/mapper/sa2py_types.py: классы SQLAlchemy нормализуются в экземпляры, а обертки Nullable и LowCardinality раскрываются до базового типа.
- Добавлены unit- и integration-тесты для Float64, Nullable(Float64) и вложенных ClickHouse-типов.

### 2026-08-12 12:38:52
- В Gateway для SQL metadata добавлена подстановка переменных проекта по шаблонам `{{ project_variables.<имя> }}` и `{{ <имя> }}` с проверкой доступа к проекту.

### 2026-08-12 18:34:00
- Рефакторинг файлового runtime для extract-нод: общие fsspec-операции и S3-диагностика перенесены в `src/node_dsl/node_mixins/file_connection`, удалено дублирование listing/path logic из `load_csv`, `load_excel`, `load_json` и `load_parquet`.
- Добавлена классификация ошибок S3 для отсутствующего бакета/пути, доступа, аутентификации, endpoint и прочих server errors; exact-path проверки используют `info()` вместо маскирующего исключения `exists()`.
- Тесты S3-диагностики перенесены на уровень `node_dsl` и расширены проверками инициализации filesystem, 404-disambiguation и сохранения AccessDenied.

### 2026-08-13 12:30:00
- Проведён анализ интеграции Dask в `src/node_dsl` и `src/pipeline`; отчёт и воспроизводимые экспериментальные скрипты добавлены в `tmp/`.

### 2026-08-13 12:40:00
- Исправлена идентификация параллельных `task_worker`: каждому запуску автоматически назначается уникальный внутренний ID, который наследуют Celery child-процессы.
- Этот же ID передаётся Celery как hostname; добавлены unit-тесты генерации ID и параметров запуска воркера.

### 2026-08-14 13:08:37
- Добавлен bounded context `src/modules/sql_template` для безопасного контекстного рендеринга SQL-шаблонов с сохранением формата `{{ input_variables.foo }}` и Jinja-фильтров.
- SQLCodeInputFieldMixin-ноды и Gateway SQL metadata переведены на безопасную сериализацию literals и identifiers; добавлены регрессии для апострофов, коллекций и диалектов ClickHouse/PostgreSQL/MSSQL.

### 2026-08-14 13:34:51
- Адаптированы unit-тесты файловых нод к FileConnectionRuntime: fake-FS теперь поддерживают info(), а Excel-тесты используют централизованный runtime вместо удаленного _list_files.
- Обновлено ожидаемое экранирование SQL-идентификаторов в тесте metadata prepass.

### 2026-08-14 14:55:27
- Удалены ORM-связи `Relationship` для проектов, расписаний и запусков расписаний при сохранении всех FK.
- Загрузка email владельца проекта переведена на явную пакетную выборку.
- Для физического удаления пользователей добавлена явная очистка зависимостей без ORM-каскадов; добавлены unit и integration тесты.

### 2026-08-14 15:17:02
- Удалены оставшиеся ORM-связи между OrganizationRecord и SubgraphRecord при сохранении FK `subgraphs.organization_id`.
- Добавлен изолированный регрессионный тест инициализации ORM-мэпперов в составе импортов Orchestrator без graph-моделей.

### 2026-08-14 15:52:14
- Исправлен unit-тест файлового хранилища: перед созданием проекта явно сохраняются организация и пользователь, чтобы соблюсти внешние ключи после удаления ORM-связей.

### 2026-08-17 15:14:59
- Обновлён экспорт пайплайна `Расходы и доходы`: устаревшие ноды чтения SQL переведены на актуальную версию, сохранены идентификаторы нод и рёбер.

### 2026-08-17 19:20:00
- Выполнен переход task execution на durable outbox и атомарный claim фактическим worker-ом; Orchestrator больше не назначает worker из памяти.
- Добавлен bounded context `task_execution`, отключен автоматический Celery retry после потери worker-а и добавлено восстановление pending сообщений Redis Streams.

### 2026-08-17 20:15:36
- Завершено развитие lifecycle выполнения задач: добавлены cooperative STOP с DB-authoritative наблюдением и эскалацией, удалена legacy Celery control queue, расширена модель свободной capacity, исправлен RELEASE marker и ordering supersession.

### 2026-08-17 23:15:00
- Исправлен race stale execution telemetry: stale-записи теперь наблюдаются без удаления, а cleanup выполняется только после authoritative terminal state или подтвержденной heartbeat-потери worker-а.
- Добавлены regression-тесты на сохранение stale record при живом worker-е, последующий WORKER_LOST, восстановление telemetry, terminal DB cleanup, CANCEL_REQUESTED и BUSY/OFFLINE capacity.

### 2026-08-18 11:47:39
- Завершён refactor Orchestrator + Task Worker + task_execution: WORKER_LOST reconciliation переведён на PostgreSQL active executions и heartbeat liveness, включая recovery после рестарта Orchestrator без telemetry.
- Исправлены executable readiness расширений и runtime generation reload persistent Celery child после install/update; локальные dependencies теперь являются execution barrier.
- Добавлена domain policy precedence termination reasons, атомарный nested-wait rebalance при падении alive capacity, fork-safe child log -> parent -> WebSocket bridge и best-effort Redis cleanup после terminal DB commit.
- Исправлен root-task coalescing по persisted queued_at + task_id для reversed enqueue arrival; расширены unit/integration regression tests для races, recovery, STOP DB polling, XAUTOCLAIM, Dask cleanup и extension runtime update.

### 2026-08-18 12:10:38
- Добавлен bounded cleanup фоновых telemetry/cancellation task в persistent Task Worker: cancellation-resistant transport больше не может бесконечно блокировать authoritative terminal DB transition.
- Усилен Celery integration: два реальных homogeneous Task Worker без forced max_tasks_per_child, задача стартует из QUEUED, а persisted assigned_worker_id совпадает с worker, реально выполнившим atomic claim.

### 2026-08-18 14:35:20
- Исправлен отказ synchronous nested execution: добавлен атомарный `PENDING -> ERROR/NESTED_WAIT_CAPACITY_LOST` flow внутри `task_execution`, а permissive lifecycle mock заменён реальным use-case regression coverage.
- Добавлено обнаружение аварийной смерти Celery prefork execution child через MainProcess `WorkerLostError` без implicit retry; intentional STOP/HARD_STOP и OOM сохраняют authoritative termination precedence, replacement child продолжает выполнять следующие задачи.
- Gateway queue cancel переведён на Orchestrator cooperative control flow, heartbeat теперь сообщает точное состояние execution slot, а capacity корректно восстанавливается после рестарта Orchestrator.
- Добавлена простая Redis Stream notification deduplication по message id, синхронизирован `ORCH_STREAM_PENDING_IDLE_SEC` в production config и усилены persistent-child extension runtime integration tests с реальной reload generation.

### 2026-08-18 18:26:59
- Обновлен unit-тест создания pending-задачи: вместо удаленного `task_crud` он подменяет lifecycle-команды `task_execution` и проверяет сохранение domain execution.

### 2026-08-18 19:12:10
- Восстановлен импорт fixture `resolved_sql_test_engine` в Redis cache integration-тестах чтения из БД, чтобы pytest корректно выполнял параметризацию по поддерживаемым SQL-движкам.

### 2026-08-18 19:33:06
- Исправлена инициализация Windows event loop policy в integration-тестах: настройка перенесена в общий ранний bootstrap `tests/integration/conftest.py`, локальные сбросы policy из fixtures и тестовых модулей удалены.

### 2026-08-18 20:03:00
- Добавлен статический анализатор `scripts/analysis/extension_imports_check.py` для проверки импортов расширений из `src`, `core` и `config.py`, включая re-export и compatibility `__getattr__`; добавлены unit-тесты и понятный полный отчёт о ненайденных сущностях.

### 2026-08-19 10:17:00
- Переведены деплои DEMO и PROD на отдельный ночной scheduled pipeline: выбирается самый свежий стабильный semver-тег без RC, версия передаётся через dotenv, а повторный деплой уже успешно установленной версии блокируется marker-файлом на стенде.

### 2026-08-19 11:35:00
- Разделён Node DSL core и runtime integrations: input value model перенесён в dependency-light `src/node_dsl/core`, connection runtime — в `src/node_dsl/runtime`, а S3-specific обработка ошибок с `botocore` изолирована в `runtime/integrations/file_connection/s3`.
- Старые import paths сохранены как compatibility aliases/lazy exports; Project Scheduler больше не требует `botocore` при импорте. Добавлены regression-тесты import boundaries.

### 2026-08-19 16:40:00
- `HTTPRequest.json_payload` расширен до JSON-объекта или массива, добавлена нормализация immutable/template значений, поддержка пустых JSON body и совместимость со старыми form-data конфигурациями.
- Общий expression runtime теперь разделяет `input_variables` и `project_variables`, сохраняя input-priority для коротких имён; HTTP auth также использует отдельные scopes. Добавлены regression-тесты payload schema, normalization и variable namespaces.

### 2026-08-19 17:07:00
- Исправлена генерация JSON Schema для сложных union-типов в `TypeResolver`: Pydantic-схема теперь строится для union целиком, поэтому `$defs` находятся в корне и локальные `$ref` корректно разрешаются.
- Добавлен regression-тест `HTTPRequest.auth`, проверяющий разрешимость всех локальных JSON Schema ссылок и предотвращающий повторение ошибки `MissingRefError` на Frontend.

### 2026-08-19 17:39:57
- Восстановлена обратная совместимость expression runtime: `input_variables` снова предоставляет исторический merged-view project + linked variables, при этом отдельный namespace `project_variables` сохранён; linked variables продолжают иметь приоритет при совпадении имён.
- Восстановлен публичный shape сложных union-схем NodeDefinition: верхнеуровневый `oneOf` содержит inline branches, а общие `$defs` остаются в корне для корректного разрешения `$ref`.
- Исправления подтверждены полными unit- и integration-suite, включая `PipelineProcessor`.

### 2026-08-19 19:04:00
- Ограничено общее ожидание READY для async gRPC-клиентов через клиентский timeout, чтобы недоступный endpoint не приводил к бесконечному ожиданию.
- Инициализация WebSocket logging в prefork Task Worker сделана best-effort с bounded timeout; недоступный Gateway больше не блокирует выполнение pipeline и не вызывает повторную задержку перед каждой задачей child-процесса.
- Добавлены regression-тесты на bounded gRPC READY и недоступный WS sink; проблемный persistent-prefork lifecycle integration test проходит с `LOG_TO_WS=true`.

### 2026-08-19 19:59:00
- Устранено дублирование console-логов prefork Task Worker: записи, повторно доставленные через multiprocessing bridge, помечаются и исключаются только из parent console sink, сохраняя доставку в остальные parent sinks.
- В multiprocessing log bridge восстановлен Loguru-совместимый тип timestamp, поэтому формат времени больше не выводится литералом `YYYY-MM-DD HH:mm:ss.SSS`.
- Недоступный WS Forward теперь инициализируется не более одного раза на persistent child; regression подтверждён unit-тестами и Linux lifecycle integration test.

### 2026-08-19 20:37:00
- Исправлено восстановление timestamp в multiprocessing log listener для записей без исходного Loguru time object: сохраняется распарсенный `datetime`, а для реальных Loguru records по-прежнему сохраняется Loguru-совместимый тип времени.
- Исправление подтверждено полным unit-suite (`2122 passed, 2 skipped`) и Linux persistent-prefork lifecycle integration test (`1 passed`).

### 2026-08-24 12:55:41
- UsrAK расширен декларативным реестром persistent token types: встроенный lifecycle и `X-API-Key` ограничены UsrAK-managed типом, а purpose-токены остаются application-managed и обрабатываются fail-closed.
- Удалён небезопасный cache API-token resolver, исправлена проверка opaque-токенов без JWT decoding и обеспечена немедленная проверка отзыва, срока действия и IP allowlist.
- Gateway переведён с monkey patch списка токенов на публичный контракт UsrAK 0.5.0; `api_token` зарегистрирован как UsrAK-managed, а `MCP` — как application-managed без изменения MCP bounded context.
- Собран и проверен wheel `usrak-0.5.0`; целевые тесты UsrAK и DVT проходят успешно.

### 2026-08-20 19:57:58
- Переработано кеширование dask.DataFrame: добавлены generation-scoped manifests и atomic active generation, lossless execution codec, lazy bounded restore с сохранением divisions, fail-open запись, TTL и защита от partial/corrupted cache.
- Оптимизированы Redis MGET/EXISTS и owner-loop cleanup, исправлены Gateway pagination/CSV пути, добавлены regression/integration тесты и before/after benchmark с отчетом в experiments.

### 2026-08-21 11:35:21
- Исправлена сериализация NumPy scalar-значений в DumpEngine с сохранением dtype, чтобы Dask SQL divisions (включая int32/int64, datetime64 и timedelta64) корректно сохранялись в generation manifest кеша DataFrame.
- Интеграционные тесты кеша ReadQueryFromDBV3 и ReadTableFromDBV3 переведены с legacy PDFKey/meta-key на проверку active generation и READY manifest; полный integration-suite подтвержден результатом 215 passed, 3 skipped.

### 2026-08-21 13:25:00
- Доведён generation-cache `dask.DataFrame` до deterministic concurrency semantics: порядок executions основан на `(queued_at, task_id)`, active generation переключается атомарным Redis/Valkey CAS через Lua и stale execution не может перезаписать более новый.
- Исправлен DataFrame cache benchmark: cache-miss теперь принудительно materialize-ит полный output и валидирует READY manifest/partitions, optimized aggregate вынесен отдельно, добавлены provenance, time-to-first-partition и RSS drift метрики; missing-partition probe переведён на generation model.
- Runtime fingerprint дополнен стабильной DVT build/version identity; усилены regression-тесты concurrency, CAS, TTL, fail-open и Gateway/cache integrity.

### 2026-08-25 18:38:03
- В `SaveParquet write_v1` заменены отдельные Dask compute для батчей на одно согласованное вычисление с bounded-memory streaming физических chunks; append теперь валидирует schema каждого существующего physical/logical файла до записи.
- `SaveParquet`/`LoadParquet` сохраняют logical schema Hive partitions в Parquet footer, восстанавливают partition dtype/values при round-trip, сохраняют lazy FTP read и усиливают семантику `write_index`, filename template, `row_cap` и `parquet_types`.
- Добавлены filesystem/round-trip/regression проверки нового режима `SaveParquet` и performance benchmark report в `experiments/`.

### 2026-08-25 20:23:29
- Добавлена integration-проверка `write_v1 -> filesystem storage -> LoadParquet` на реальном временном filesystem для Simple, increment/UUID, row_cap, Hive partitioning, append с дыркой, create preflight и schema mismatch preflight.
- Integration regression отдельно проверяет отсутствие `_metadata`, `_common_metadata` и каталогов с суффиксом `.parquet`.

### 2026-08-26 10:39:00
- Исправлены correctness-blockers `SaveParquet write_v1`: partitioning по всем data columns больше не теряет row count, а пустой partitioned dataset получает читаемый zero-row sentinel с logical schema/footer marker и остаётся append-compatible.
- Hive partition values теперь до создания path приводятся через объявленный Arrow type, зарезервированный NULL sentinel запрещён как literal; добавлены безопасный dictionary/category discovery для filesystem/S3 и dataset-wide categorical meta для FTP без подмены значений на `NaN`.
- Расширены filesystem/S3/FTP regressions на typed partitions, categorical/null values, append новой категории и cleanup; устранены замечания Ruff в затронутом Parquet/SMB test-коде.

### 2026-08-26 13:00:17
- В `SaveParquet write_v1` восстановлена активация DVT-Dask public operation callbacks вокруг единого delayed computation без изменения Simple ordering и Advanced parallelism; повторно активный `PublicOperationCallbacks` не создаёт второй lifecycle.
- Добавлены regressions для success/error lifecycle, `DFOutputBaseNode` callback/cache metadata, физического порядка Simple row groups и однократного shared upstream execution в Simple/Advanced/row_cap/partition_on.
- Повторён benchmark с callback counters: во всех 12 runs получены `on_start=1`, `on_end=1`, `on_error=0`, 16/16 уникальных partition callbacks и shared upstream execution = 1 без заметной деградации wall time/RSS; полные unit/integration suites зелёные.

### 2026-08-26 14:24:18
- Исправлен URL MinIO по умолчанию в интеграционном тесте SaveParquet: для локального тестового сервиса на порту 3900 используется HTTP вместо HTTPS.

### 2026-08-26 18:40:07
- Исправлена семантика dual-role Dask index для Read DB V3 downstream: явный Drop partition column переводит физический индекс во внутреннее имя `__dvt_partition_key`, сохраняя divisions и не оставляя удалённое business-поле в metadata.
- Writer V3/V4 теперь различают внутренний DVT index, совпадающий business column/index и настоящий user index-only field: внутренние индексы не материализуются, collision использует ordinary column, а genuine index сохраняет прежнее `reset_index`-поведение.
- Добавлены regressions для Read/Rename/Drop/Filter/Select/Join и обоих DB writers; indexed Join сохраняет known divisions и обходится без shuffle. Полные suites: unit `2274 passed, 2 skipped`, integration `222 passed, 3 skipped`.

### 2026-08-26 20:21:43
- Для обычного и post-deploy запуска integration-тестов добавлен общий preflight внешней Docker-сети `dvt-net`: сеть создаётся идемпотентно перед `docker compose run`, включая безопасную обработку конкурентного создания.
- Добавлены unit-тесты для сценариев существующей и отсутствующей сети.

### 2026-08-28 11:18:00
- Для Debian-based Docker build stages добавлен общий APT mirror fallback: `deb.debian.org` остаётся основным источником, а `mirror.yandex.ru` используется как резервный через штатный `mirror+file` transport с приоритетами.
- Fallback подключён к базовым DVT images, ODBC/dependency build stages и Installation Manager, чтобы сетевой сбой основного Debian mirror не ломал последующие `apt-get` в prod/dev сборках.

### 2026-08-31 19:53:14
- Исправлен nightly pipeline обновления Demo/PROD: посторонние dev/release/maintenance/failure-analysis jobs исключаются из scheduled stable deploy, а maintenance manual jobs больше не блокируют завершённые pipelines.
- Добавлен отдельный ручной `deploy_prod_now` для `main` с подтверждением, немедленным запуском через `needs: []` и выбором `latest-stable` либо конкретного стабильного `X.Y.Z`; RC и другие нестабильные версии запрещены до начала PROD deploy.
- Добавлены CI regression-тесты для nightly isolation, optional maintenance, manual PROD deploy и строгого выбора стабильной версии.

### 2026-08-31 16:25:05
- Сервис `demo_provisioning` вынесен из backend-монорепозитория в самостоятельный репозиторий `dvt-demo-provisioning`; из DVT удалены его runtime/build/deploy ownership, unit-тесты, launcher, compose и provisioning-specific CI wiring.
- Общие B24 notifications и failure-analysis framework сохранены без переноса в standalone сервис.

### 2026-08-31 18:16:17
- Захардкоженный Bitrix24 webhook удалён из всех TOML-конфигов `.ci/b24_messages`; `send_b24_message.py` теперь получает его только из CI-переменной окружения `B24_HOOK`.
- Добавлены unit-регрессии на загрузку webhook из окружения и ошибку при отсутствии `B24_HOOK`.

### 2026-09-01 14:07:18
- Убраны захардкоженные JWT-секреты из production auth-кода Gateway и добавлена fail-fast проверка production-конфигурации.
- Installation manager теперь генерирует, сохраняет и безопасно дополняет JWT-секреты и salt; добавлены compose-настройки, тесты и инструкция по ротации.

### 2026-09-01 14:58:35
- Добавлены LICENSE с каноническим неизменённым текстом GNU AGPLv3 и COPYING с дополнительным разрешением DVT Extension Exception для независимых extensions через документированные extension interfaces без ослабления copyleft для DVT Core.

### 2026-09-01 15:41:35
- Полезный локальный функционал dvt_mcp перенесен в project skill dvt-project-ops с Docker-операциями, диагностикой логов и задач, безопасными DB fixture workflows и обновлением changelog. Удалены сервис dvt_mcp и кастомный PyCharm plugin, очищены конфигурация, зависимости, документация и устаревшие тестовые исключения.

### 2026-09-01 17:03:38
- Заменён сервис images_publisher на release-поток Docker Buildx Bake: публикация stable/RC образов перенесена в tag-only CI job release_images, удалены legacy build_prod/publish_images и E2E jobs, сохранён локальный UI_BUILD_CONTEXT и закреплён services/ui для официальных релизов.

### 2026-09-01 18:01:50
- Проведён review миграции публикации Docker-образов на Buildx Bake: добавлена валидация release-тега, устранён небезопасный пропуск prod-сборки перед integration tests и удалён устаревший unit-тест, зависевший от ранее удалённого tests/e2e.

### 2026-09-01 19:01:27
- Релизный Docker CI переведен на Build Once → Test Exact Candidate Images → Promote Without Rebuild: добавлена pipeline-specific candidate-сборка, integration tests используют registry images текущего pipeline, а финальные version/latest tags назначаются через Buildx imagetools с проверкой digest.

### 2026-09-01 19:41:51
- Усилена целостность release flow Build Once: candidate-образы фиксируются по digest, integration tests используют immutable refs, а promotion выполняется по протестированным digest без пересборки; дополнительно проверены dev/prod сборки и dry-run публикации.

### 2026-09-02 23:51:08
- Проверено разделение публичных GitHub-исходников и приватного GitLab CI/CD. Исправлены безопасная передача source metadata, привязка DVT_BUILD_ID к SOURCE_SHA и Python 3.13 loader тестов GitHub bridge; удалена устаревшая приватная GitLab-ссылка из публичной документации.

### 2026-09-03 13:17:22
- Обновлены canonical GitHub URL Backend и UI перед публикацией: Denvic-Tech/dvt и Denvic-Tech/dvt-ui.

### 2026-09-04 14:31:10
- Корневой README переработан для публичного GitHub: добавлены краткое описание DVT, основные возможности, быстрый запуск, архитектура, ссылки на разработку и лицензирование. Предыдущее подробное руководство перенесено в docs/DEVELOPMENT.md и адаптировано к новому расположению.

### 2026-09-04 18:34:56
- Исправлены регрессии unit-тестов: AI MCP маршруты теперь всегда присутствуют в Gateway/OpenAPI и блокируются runtime-проверкой при отключенной функции; удален устаревший license_verifier из тестов Installation Manager; миграции расширений не обращаются к БД при отсутствии migrations и изолированы mock-объектом в unit-тестах; удален неиспользуемый legacy WorkerIDManager и его тесты.
