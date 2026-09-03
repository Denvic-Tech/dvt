# `core/db/read_v3`

## Кратко
`read_v3` — строгий слой чтения данных из БД в Dask DataFrame с **известными divisions** и явным планом выполнения.

Пакет нужен для случаев, когда важно:
- детерминированно разрезать чтение на партиции;
- контролировать индекс и границы каждой партиции;
- получать предсказуемое поведение на разных SQL-диалектах;
- ловить ошибки конфигурации/планирования/исполнения на раннем этапе.

Точка входа в API пакета: [`__init__.py`](__init__.py).

---

## Высокоуровневое описание работы

### 1. Что приходит на вход
Чтение запускается через:
- `resolve_planner(mode="table" | "query")` из [`resolver.py`](resolver.py);
- `planner.build_plan(...)` из [`planner/table.py`](planner/table.py) или [`planner/query.py`](planner/query.py);
- `resolve_executor(engine)` и `frame_from_executor(...)` из [`dask.py`](dask.py).

Основные пользовательские параметры:
- режим: `table` или `query`;
- `partition_col` (обязателен для `query`, обязателен для `table` через явное поле или single-column PK);
- `npartitions`, `limit`, `max_rows_per_partition`;
- `partition_grouping` (кастомное разбиение).

Если `npartitions` не передан, `read_v3` сам рассчитывает его внутри planner'а через memory-aware estimator.
Оценка учитывает:
- реальный/оценочный `bytes per row`;
- `config.DASK_PARTITIONING.*`;
- `limit`, если он задан;
- диалектные batch-size эвристики.

### 2. Алгоритм по шагам
1. Выбирается SQL-диалект (`resolve_dialect`) из [`dialects/__init__.py`](dialects/__init__.py).
2. Планировщик собирает метаданные (колонки, типы, ключ партиционирования, row stats).
   Если `npartitions=None`, на этом же этапе planner оценивает размер чтения и подбирает число партиций.
3. Выбирается стратегия:
- авто (`range` для orderable non-null ключа, иначе `hash`) через [`partitioning/adapters.py`](partitioning/adapters.py);
- или явная (`partition_grouping.mode = range/hash`);
- или кастомная группировка (например, `prefix`, `step`, `granularity`, `explicit_values`) через [`partitioning/grouping.py`](partitioning/grouping.py).
4. Строятся `segments` + `divisions`.
5. `frame_from_executor` проверяет, что сегменты не пустые и divisions валидны.
6. Dask создаёт граф из `delayed(executor.load_partition(...))`.
7. Каждая партиция читается SQL-запросом с `WHERE`-предикатом сегмента.

### 3. Поведение на пустых таблицах
- Для range-планирования уже есть fallback на один пустой сегмент (`predicate_sql = "1=0"`), см. [`planner/boundaries.py`](planner/boundaries.py).
- Для кастомной grouping-ветки (`partition_grouping`, например `mode="prefix"`) при `total_rows == 0` также создаётся **одна пустая партиция** (`divisions = (0, 1)`), см. [`partitioning/grouping.py`](partitioning/grouping.py).

### 4. Когда выбрасываются ошибки
Иерархия ошибок в [`errors.py`](errors.py):
- `ReadV3ConfigError`: некорректная конфигурация.
  Примеры:
  - `query` без `partition_col`;
  - `limit <= 0`;
  - неподдерживаемый `partition_grouping.mode`;
  - `range` для nullable ключа.
- `ReadV3PlanningError`: не удалось построить строгий план.
  Примеры:
  - колонка не найдена;
  - невалидные или немонотонные divisions;
  - диалект/данные не позволяют построить необходимые границы.
- `ReadV3ExecutionError`: ошибка исполнения сегмента.
  Примеры:
  - сегмент вернул больше строк, чем `max_rows_per_partition`;
  - индекс сегмента нарушает границы division;
  - в результате отсутствуют обязательные колонки.
- `ReadV3DialectError`: неподдерживаемый SQL-диалект.

---

## Низкоуровневое устройство

### Контракты данных
Основные dataclass-модели в [`models.py`](models.py):
- `ReadV3Plan`: полный план чтения;
- `ReadSegment`: один сегмент чтения (`predicate_sql`, `division`, `expected_rows`, ...);
- `SegmentDivision`: границы сегмента;
- `PartitionStrategy`: `range`/`hash`;
- `ValueKind`: тип ключа (numeric/date/datetime/string/bool/uuid/unknown).

### Планирование (`planner/*`)
#### `TableReadPlanner`
Файл: [`planner/table.py`](planner/table.py)
- introspection таблицы через SQLAlchemy inspector;
- разрешение колонок и ключа;
- вычисление `min/max/total/non_null` через [`planner/boundaries.py`](planner/boundaries.py);
- при `npartitions=None` использует внутренний memory-aware estimator:
  - сначала метаданные таблицы/колонок, если диалект их даёт;
  - затем sample/fallback-эвристики по типам;
  - tuning берётся из `config.DASK_PARTITIONING.*`;
- построение `segments`:
  - `build_range_segments` (range);
  - `build_hash_segments` (hash);
  - `build_grouping_segments` (custom grouping).

#### `QueryReadPlanner`
Файл: [`planner/query.py`](planner/query.py)
- приводит query-mode к relation-like источнику через внутренний `user_query`;
- для MSSQL поддерживает plain `SELECT` и top-level `WITH ... SELECT`;
- не поддерживает SQL batches/scripts (`DECLARE`, temp tables, `EXEC`, несколько statement'ов);
- извлекает схему результата и пытается определить типы колонок под разные драйверы;
- при `npartitions=None` использует тот же internal estimator, но BPR берёт из sample по query-source;
- дальше использует ту же механику сегментации, что и table-mode.

### Группировка (`partitioning/grouping.py`)
- использует локальный grouping-builder `read_v3/grouping/*`;
- преобразует внутренние grouping-сегменты в `ReadSegment`;
- гарантирует, что на выходе есть валидный набор сегментов/делений (включая empty fallback).

### Исполнение (`executors/*`)
- Интерфейс `Executor` в [`executors/base.py`](executors/base.py).
- Основная реализация в [`executors/sql.py`](executors/sql.py):
  - формирует SQL по сегменту;
  - читает с ограничением `max_rows_per_partition + 1`;
  - валидирует границы индекса;
  - удаляет служебные helper-колонки (`__dvt_*`) из финального output;
  - строит `meta` с ожидаемыми dtypes.
- Для ClickHouse используется отдельный class-name-обёртка [`executors/ch.py`](executors/ch.py).

### Интеграция с Dask
Файл: [`dask.py`](dask.py)
- запрещает пустой execution graph;
- валидирует divisions;
- собирает `dd.from_delayed(..., divisions=..., verify_meta=False)`.

---

## Примеры

### Таблица (table mode)
```python
from core.db.read_v3 import resolve_planner, resolve_executor, frame_from_executor
import config

planner = resolve_planner(mode="table")
plan = planner.build_plan(
    engine=engine,
    table_name="events",
    partition_col="id",
    npartitions=8,
    columns=["id", "event_type", "created_at"],
    min_rows_per_partition=config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    target_partition_mem_mb=config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    partitioning_overhead_coef=config.DASK_PARTITIONING.OVERHEAD_COEF,
    max_partitions=config.DASK_PARTITIONING.MAX_PARTITIONS,
)

executor = resolve_executor(engine)
ddf = frame_from_executor(executor, plan)
df = ddf.compute()
```

### Запрос (query mode) с grouping
```python
import config

planner = resolve_planner(mode="query")
plan = planner.build_plan(
    engine=engine,
    query="SELECT id, category, created_at, value FROM events",
    partition_col="category",
    partition_grouping={"mode": "prefix", "length": 1},
    npartitions=4,
    min_rows_per_partition=config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    target_partition_mem_mb=config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    partitioning_overhead_coef=config.DASK_PARTITIONING.OVERHEAD_COEF,
    max_partitions=config.DASK_PARTITIONING.MAX_PARTITIONS,
)
```

---

## Как расширять

### 1. Добавить новый SQL-диалект
1. Создать класс диалекта в `dialects/<new_db>.py`, унаследовать `SQLDialect` из [`dialects/base.py`](dialects/base.py).
2. Реализовать минимум:
- `quote_ident`;
- `limit_offset`;
- `hash_expr`.
3. При необходимости реализовать:
- `string_prefix_expr` (для `partition_grouping.mode=prefix`);
- `quantile_expr` (для quantile-grouping).
4. Подключить в [`dialects/__init__.py`](dialects/__init__.py) в `resolve_dialect`.
5. Добавить unit/integration тесты.

### 2. Добавить новый режим grouping
1. Расширить локальные модули в `read_v3/grouping/*` (`spec.py`, `builder.py`, при необходимости `models.py` / `temporal.py`).
2. При необходимости обновить рендер предикатов в `_render_segment_predicate` в [`partitioning/grouping.py`](partitioning/grouping.py).
3. Добавить тесты:
- unit в `tests/unit/core/db/read_v3/`;
- integration в `tests/integration/core/db/read_v3/`.

### 3. Добавить новую стратегию/планировщик
1. Обновить `PartitionStrategy` в [`models.py`](models.py).
2. Добавить логику выбора в [`partitioning/adapters.py`](partitioning/adapters.py).
3. Реализовать построение сегментов в `planner/*`.
4. Убедиться, что `executors/sql.py` умеет выбрать индекс и валидировать границы для новой стратегии.

### 4. Практический checklist после изменений
1. Проверить инварианты divisions (`len == segments + 1`, монотонность, без `None`).
2. Проверить поведение на:
- пустой таблице;
- nullable ключе;
- `limit`;
- кастомной grouping.
3. Прогнать релевантные тесты `tests/unit/core/db/read_v3` и `tests/integration/core/db/read_v3`.
