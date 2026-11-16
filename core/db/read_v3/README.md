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
- `resolve_executor(engine)` и `frame_from_executor(...)` из [`dask.py`](dask.py);
  `resolve_executor(engine, max_concurrent_queries=N)` ограничивает число одновременных запросов
  партиций этого executor'а (семафор вокруг вызова runner'а), независимо от пула потоков потребителя.

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
  - диалект/данные не позволяют построить необходимые границы;
  - сегмент кастомной группировки больше `max_rows_per_partition` и не может быть разбит
    (группа `__null__`, группа из одного значения ключа, диалект без `hash_expr`, разбиение
    превысило бы `max_partitions`);
    ошибка называет сегмент, его число строк и причину и возникает до чтения данных;
  - самое частое значение ключа или группа `NULL` больше `max_rows_per_partition` при
    `range`/`hash` (см. «Перекос ключа и рекомендации по партиционированию»).
- `ReadV3ExecutionError`: ошибка исполнения сегмента.
  Примеры:
  - сегмент вернул больше строк, чем `max_rows_per_partition` (например, одно значение ключа
    повторяется чаще потолка или hash-разбиение получилось неравномерным); сообщение содержит
    метку сегмента;
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
- при `npartitions=None` использует внутренний memory-aware estimator
  (`estimate_table_bytes_per_row` в [`_auto_partition.py`](_auto_partition.py)):
  - сначала ширины колонок из каталога: ClickHouse — `system.parts_columns`,
    `sum(column_data_uncompressed_bytes) / sum(rows)` по активным Wide-частям (у Compact-частей
    размеров колонок нет; `data_uncompressed_bytes` там — размер всей части в строке каждой колонки,
    из-за чего ширина раньше завышалась в число колонок раз: 2087 вместо 231 байта на 10 колонках);
    PostgreSQL — `pg_stats.avg_width` таблицы, найденной через `CAST(<имя в кавычках> AS regclass)`
    (с учётом `search_path`, строка `inherited` в приоритете), то есть только после `ANALYZE`;
    Oracle — `USER_TAB_COLUMNS.AVG_COL_LEN`; колонка без статистики получает ширину по типу;
  - затем sample из 1000 строк (`memory_usage(deep=True)`) и эвристики по типам;
  - к сумме применяются `TABLE_BPR_SAFETY_COEF` и `ROW_OVERHEAD_BYTES`, формула числа партиций
    (`finalize_partition_estimate`) от источника ширины не зависит;
  - tuning берётся из `config.DASK_PARTITIONING.*`;
- построение `segments`:
  - `build_range_segments` (range): границы — значения ключа на 0-based позициях
    `0, page_size, 2 * page_size, ...` отсортированных не-NULL значений
    (`page_size = ceil(non_null_rows / npartitions)`), одинаковые соседние границы схлопываются.
    Все границы читает один запрос `SQLDialect.range_boundaries_query`: ClickHouse —
    `row_number() OVER (ORDER BY key ROWS BETWEEN CURRENT ROW AND CURRENT ROW)` с фильтром
    `(rn - 1) % page_size = 0` (одна сортировка; `quantilesExact` с сотнями уровней в десятки раз
    медленнее и не принимает String/UUID/Date32), PostgreSQL —
    `percentile_disc(ARRAY[(r + 0.5) / N, ...]) WITHIN GROUP (ORDER BY key)` (дробь середины
    позиции выбирает ту же строку, что `OFFSET r`), SQL Server, MySQL 8 / MariaDB 10.2+, Oracle —
    `ROW_NUMBER()` с фильтром по остатку. SQLite (`NotImplementedError`), ошибка запроса или пустой
    результат переводят на прежний цикл `boundary_query` (`ORDER BY key LIMIT 1 OFFSET r` на каждую
    границу) с warning в логе; способ попадает в `plan.warnings` как
    `range_boundaries=single_query|offset_loop|offset_loop(single query failed: ...)`.
    Значения и их типы совпадают с OFFSET-циклом, поэтому сегменты те же. 600 границ по
    неотсортированному ключу таблицы ClickHouse на 49,69 млн строк: 186,8 с → 1,7 с;
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
- planner вычисляет потолок `max_rows_per_partition` до построения сегментов (явное значение или
  `max(100_000, 4 * ceil(total_rows / npartitions))`) и передаёт его вместе с `max_partitions`;
- группа с точным числом строк `count > max_rows_per_partition` заменяется
  `k = ceil(count / floor(0.8 * max_rows_per_partition))` подсегментами с предикатом
  `(<предикат группы>) AND <hash_expr(ключ, k)> = i`, метками `<метка>#i/k` и
  `expected_rows = ceil(count / k)`; hash считается по полному значению ключа, а не по выражению
  группы (например, префиксу);
- не разбиваются группа `__null__`, группа из одного значения ключа (`value_expr is None` и ровно
  одно значение в `include_values`: `as_is`, одно значение `explicit_values`, bool-группы) и группы
  диалекта, у которого `hash_expr` бросает `NotImplementedError`; если разбиение дало бы больше
  `max_partitions` сегментов, группы тоже не разбиваются. Во всех этих случаях оставшийся слишком
  большой сегмент даёт `ReadV3PlanningError`;
- одинаковые значения ключа внутри группы-префикса, периода или диапазона hash не разносит,
  поэтому ограничение `max_rows_per_partition + 1` в executor остаётся последней проверкой; автоматические `range`/`hash`-сегменты с оценочным
  числом строк не разбиваются, до чтения проверяется только самое частое значение ключа;
- гарантирует, что на выходе есть валидный набор сегментов/делений (включая empty fallback).

### Перекос ключа и рекомендации по партиционированию
Файлы: [`planner/key_skew.py`](planner/key_skew.py), [`key_stats.py`](key_stats.py),
[`partition_advice.py`](partition_advice.py).

**Проверка при планировании.** Range-границы и hash-buckets не делят строки с одним значением
ключа, а все `NULL` попадают в один bucket. Поэтому перед построением автоматических или явных
`range`/`hash`-сегментов, если `total_rows > max_rows_per_partition`, planner один раз ищет самое
частое значение ключа (`check_partition_key_skew`):
- ClickHouse: точный `SELECT key, count() ... GROUP BY key ORDER BY count() DESC LIMIT 1`
  (`SQLDialect.heaviest_value_query`); на 49,69 млн строк — около 0,6 с;
- PostgreSQL, table mode без `limit`: оценка из `pg_stats` (`most_common_freqs[1]` и `null_frac`,
  умноженные на число строк); ошибка только при превышении потолка более чем на 25%;
- остальные диалекты и query mode PostgreSQL: проверка пропускается, последним рубежом остаётся
  проверка строк сегмента в executor.

Если значение (или группа `NULL`) больше потолка, `ReadV3PlanningError` называет ключ, значение,
число строк, потолок и предлагает другой ключ или больший `max_rows_per_partition`, ссылаясь на
`suggest_read_partitioning`. Ошибки самого запроса проверки не блокируют план. Статус попадает в
`plan.warnings` как `key_skew_check=...`. Проверку отключает параметр планировщика
`key_skew_check=False`; ноды передают `config.DASK_PARTITIONING.READ_V3_KEY_SKEW_CHECK`
(переменная `READ_V3_KEY_SKEW_CHECK`, по умолчанию `true`). Кастомная группировка проверяется
своим механизмом (см. выше) и сюда не входит.

**Статистика ключей** (`collect_key_statistics`) адресует relation так же, как планировщики
(таблица или `WITH user_query AS (...)`), и возвращает dataclass-ы: итог relation (строки, оценка
ширины строки читаемых колонок тем же estimator, ключ сортировки ClickHouse
`system.tables.sorting_key` или PK/ведущие колонки btree-индексов через inspector) и по каждому
кандидату тип, distinct, самое частое значение и его число, `NULL`, min/max, `indexed`, `source`,
`estimated`. Relation до `READ_V3_KEY_STATS_SAMPLE_ROWS` строк (по умолчанию 1 000 000)
профилируется точно, большая — оценками:
- ClickHouse: точный режим — один `UNION ALL` из `GROUP BY` по каждому кандидату
  (`key_stats_query`); выше порога — один проход `uniq`/`countIf(isNull)`/`min`/`max` по всей
  relation (`key_aggregates_query`) и тот же `GROUP BY` по выборке (`SAMPLE n` при ключе
  сэмплирования, иначе `WHERE rand() < ...`), число самого частого значения масштабируется;
- PostgreSQL, таблица: `pg_stats` (последний ANALYZE), иначе `TABLESAMPLE SYSTEM (...) REPEATABLE`;
- MSSQL — `TABLESAMPLE (... PERCENT) REPEATABLE`, Oracle — `SAMPLE (...) SEED`, MySQL/SQLite и
  query mode — первые строки (`cap_rows_sql`); счётчики масштабируются, distinct — по выборке.
  Два запроса на колонку: профиль `GROUP BY` и самое частое значение. Ошибка выборки переводит на
  первые строки, ошибка колонки помечает её `available=false`.

**Рекомендации** (`advise_partitioning`, без I/O): `target_npartitions` и строки на партицию
считаются как в planner (`finalize_partition_estimate` или явный `npartitions`), потолок —
`max(100_000, 4 * rows_per_partition)` или явный. Исключаются колонки, у которых самое частое
значение или группа `NULL` больше потолка (с нужным потолком и памятью сегмента в причине) и
distinct меньше `target_npartitions`. Порядок: целые/даты/datetime с перекосом не выше 4
(`max_repeat / (non_null / distinct)`), затем прочие упорядочиваемые, затем строки и UUID; внутри —
range раньше hash, ключи без `NULL` раньше, затем меньший перекос. `range` — только если relation отсортирована или
проиндексирована по колонке и в ней нет `NULL`, иначе `hash` с `buckets = target_npartitions`.
`max_rows_per_partition` рекомендации — явный или
`max(потолок, 2 * (rows_per_partition + max_repeat))`. Даты и datetime получают оценочный
`granularity_option`: самый крупный период, у которого равномерная оценка строк не выше потолка.
Gateway отдаёт это через `POST /db-connections/{connection_id}/partitioning-advice` и
MCP-инструмент `suggest_read_partitioning`.

### Исполнение (`executors/*`)
- Интерфейс `Executor` в [`executors/base.py`](executors/base.py).
- Основная реализация в [`executors/sql.py`](executors/sql.py):
  - формирует SQL по сегменту;
  - читает с ограничением `max_rows_per_partition + 1` через хук `_fetch_segment_df`
    (по умолчанию `sql_runner.query_df`);
  - валидирует границы индекса; индекс range-плана по дробному ключу Decimal/numeric (divisions —
    `Decimal`) берётся из значений ключа до приведения колонок к float64, поэтому индекс и
    divisions сравниваются точно (float64 от `Decimal('190.6666')` меньше самой границы);
    meta-индекс такого плана — `object`;
  - удаляет служебные helper-колонки (`__dvt_*`) из финального output;
  - строит `meta` с ожидаемыми dtypes.
- ClickHouse: [`executors/ch.py`](executors/ch.py) переопределяет `_fetch_segment_df`.
  - Запросы сегментов идут через пул клиентов `clickhouse_connect` одного executor'а
    (не больше `max_concurrent_queries` простаивающих клиентов, без лимита — 4). Создание
    клиента стоит нескольких запросов к серверу (версия и timezone, `system.settings`, проверка
    протокола; ~0,1–0,2 с), поэтому клиент не создаётся на каждый сегмент. Клиент одновременно
    выполняет только один запрос (у него своя HTTP-сессия); все клиенты используют общий
    ограниченный urllib3 PoolManager процесса. Клиент, запрос которого упал, не переиспользуется.
    Планирование и метаданные (`DESCRIBE`, границы, `build_meta`) по-прежнему создают клиента
    на запрос через `sql_runner`.
  - Если тип каждой колонки результата (`plan.output_column_type_repr`, для служебной колонки
    ключа — `partition_key_type_repr`) входит в список ниже, сегмент читается в формате Arrow
    (`raw_query(fmt="Arrow")`, IPC декодируется в `pa.system_memory_pool()`: пул Arrow по
    умолчанию (mimalloc) удерживал память между потоками dask и поднимал пиковый RSS) и
    поколоночно приводится к тем же dtypes и значениям, что дал бы
    `query_df`: `Int8`–`Int64`, `UInt8`–`UInt64`, `Float32`, `Float64`, `Bool`, `String`,
    `Date`, `Date32`, `DateTime`, `DateTime(tz)`, `DateTime64(p)`, `DateTime64(p, tz)`,
    `Decimal(P, S)`, `Decimal32/64/128/256(S)`, в том числе внутри `Nullable(...)` и
    `LowCardinality(...)`. Соответствие: `Nullable` целые — pandas `Int*`/`UInt*` той же
    ширины; `Nullable(Float32)` — `float64`; строки — `pd.StringDtype()` с `<NA>`; `Bool` —
    `bool` или `object` при наличии NULL; `Decimal` — объекты `Decimal`; даты и время —
    `datetime64[ns]`, с timezone колонки или сервера (как `query_df`), без timezone, если она UTC.
  - Любой другой тип (`FixedString`, `UUID`, `Enum*`, `IPv4/IPv6`, `Int128/256`, `UInt128/256`,
    `Array`, `Map`, `Tuple`, `Nested`, `JSON`, `Object`, геотипы, `AggregateFunction`, пустой
    или нераспознанный тип) отправляет весь сегмент через `query_df`.
  - Если результат Arrow нельзя привести без расхождения с `query_df` (невалидный UTF-8,
    который `query_df` отдаёт hex-строкой, дата вне диапазона `datetime64[ns]`, неожиданный тип
    Arrow), сегмент перечитывается через `query_df` с предупреждением в логе.
  - `DateTime64` с точностью не 0/3/6/9 `query_df` не читает (`ProgrammingError`), а путь Arrow
    читает.

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
- `quantile_expr` (для quantile-grouping);
- `heaviest_value_query`, `column_statistics_query`, `table_sort_key_query`, `key_stats_query`,
  `key_aggregates_query`, `key_sample_relation` (проверка перекоса и статистика ключей;
  по умолчанию `NotImplementedError` или общий SQL на первых строках).
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
