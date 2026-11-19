# Task Benchmarking Service

Runs a pipeline from JSON and reports process RSS usage plus execution time overall and per node.

## Pipeline files

Input scenarios are stored in `services/task_benchmarking/pipelines/`:

- `examples/sample_pipeline.json`: DB-free smoke run, 200 000 synthetic rows counted by
  `BenchmarkMaterialize`.
- `benchmarks/write/<postgres|clickhouse|mssql|mysql>/append_1m.json`, `append_5m.json`: synthetic
  `wide_mixed` rows (1M in 16 partitions, 5M in 64 partitions) appended by `WriteDataFrameToDBV4`
  (`sync_column_descriptions=false`) into `bench_write_wide`, which `BenchmarkEnsureTable`
  recreates before every run. `append_wide_text_160k.json` (160 000 `wide_text` rows, about
  8 KB each, in 8 partitions) and `append_numeric_5m.json` (5M `numeric` rows in 8 partitions)
  are the wide-row and narrow-row variants. `two_branches_5m.json` (PostgreSQL and ClickHouse)
  appends two independent 5M-row sources (seeds 42 and 44) into `bench_write_a` and
  `bench_write_b`: `--outputs write_a write_b` writes them one after another in one process,
  `--outputs write_a` / `--outputs write_b` in two processes writes one each. Every write scenario carries `chunksize=1000` as the
  node form saves it (the node ignores it) and `rows_per_batch=null` (automatic batch size;
  1000 rows under `DB_CONCURRENCY_POLICY=legacy`); the ClickHouse ones also set
  `async_insert=false`. Matrix `node_overrides` such as `write.rows_per_batch` or
  `write.async_insert` replace them. An override applies only to an input that is present in the
  pipeline file.
- `benchmarks/read/<postgres|clickhouse|mssql>/full_5m.json`: `ReadTableFromDBV3` of the seeded
  `bench_wide_5m` table (64 range partitions on `id`), rows counted per partition.
- `benchmarks/read/<db>/preview_full_5m.json`: the same read collected into one pandas DataFrame;
  needs RAM for the whole table.
- `benchmarks/read/<db>/groupby_5m.json`: the same read followed by `DataFrameGroupByAgg`
  (`sum(amount)` and `count(id)` by `str_low`).
- `benchmarks/matrix/write_rows_per_batch.yaml` (`write.rows_per_batch` auto/1000/20000/100000) and
  `benchmarks/matrix/read_npartitions.yaml` (`read.npartitions` 16/64/256), both on PostgreSQL.
- `benchmarks/transform/<scenario>.json`: DB-free transform scenarios, `BenchmarkSyntheticDataFrame`
  (node `data`, 1M `wide_mixed` rows in 16 partitions) → built-in `src/nodes/transform` node(s) →
  `BenchmarkMaterialize` (`materialize`, `count_rows`, 8 threads). `baseline` has no transform and
  measures generation alone; subtract it from the other scenarios. Scenarios:
  - row-wise, one node each: `filter_10pct`/`filter_90pct` (`int_a < 100000`/`< 900000`),
    `select_columns`, `rename_columns`, `add_column_arith` (`float_a * float_b + amount`),
    `add_column_string` (`str_high.str.upper()`), `cast_column_type` (`float_b`→`Int64`,
    `int_a`→`float64`, `id`→`string`), `fill_na` (`int_b` min, `str_null` ffill), `replace_values`
    (`str_low`), `regex_replace` (`[0-9]` in `str_high`), `query`, `exec_code`, `add_time_delta`
    (`ts_a` + 7 days), `period_start_month` (`ts_a`), `split_columns` (`str_low` on `_`);
  - `chain10_mixed` (ten different row-wise nodes in a row) and `chain10_rename` (ten renames, graph
    overhead only);
  - heavy: `groupby_low` (20 `str_low` groups), `groupby_key10` (`key` with 10% distinct values:
    `data.key_cardinality` must be `rows / 10`), `groupby_key10_nunique`, `join_dim_inner`/`left`
    (`key` with 1000 values × 800-row `dim` table in one partition, renamed `id`→`dim_key`),
    `join_fact_inner`/`left` (on unique `id` with `data2`: 0.9 × rows, seed 43), `sort_numeric`
    (`float_a`), `sort_string` (`str_high`), `set_index_random` (`int_a`), `set_index_sorted` (`id`),
    `pivot_date` (`date_a` × `str_low`, `sum(amount)`), `unpivot` (3 columns), `union` (`data2`
    of the same size, seed 43), `lag_columns`;
  - pipeline shape: `shared_upstream_one_sink`/`shared_upstream_two_sinks` (the `join_fact_inner`
    upstream with one sink or with a second sink `materialize_b`).

- `benchmarks/stages/*.json`: DB-free multi-branch scenarios for staged (multi-process) execution
  measurements. Sources default to 1M `wide_mixed` rows in 16 partitions; scale them with `--set`
  as in the transform scenarios. Choose the variant with `--outputs`:
  - `two_branches_join.json` (`data_a` ⋈ `data_a2` → `sink_a`, `data_b` ⋈ `data_b2` → `sink_b`,
    seeds 42–45, no shared upstream) and `two_branches_period.json` (`data_a`/`data_b` →
    `DataFrameConvertToPeriodStart` → `sink_a`/`sink_b`). `--outputs sink_a sink_b` runs the
    branches one after another in one process, `--outputs sink_a` / `--outputs sink_b` in two
    processes runs one branch each, `--outputs sink_ab` computes both in one `dask.compute`.
  - `fanout_inline.json`: shared upstream `data` ⋈ `data2` → `select` (14 columns) fanned out
    to branch A (`sort_a` by `str_high` → `period` → `sink_a`) and branch B (`unpivot` of
    `float_a`/`float_b`/`amount` → `group_b` by `variable` → `sink_b`). Branch A sorts before
    `period` because `DataFrameJoin` → `DataFrameSelectColumns` → `DataFrameConvertToPeriodStart` →
    `DataFrameSortValues` hung in the sink compute on the former `dvt-dask` fork (its operation
    callbacks waited forever); the order is kept so results stay comparable. `--outputs sink_a sink_b`
    computes the upstream once per sink; `--outputs sink_ab` computes both branches in one
    `dask.compute` (shared upstream once); `--outputs materialize_u` computes the upstream alone;
    `--outputs store_write` computes it and writes the barrier store;
    `--outputs store_write r_sink_a r_sink_b` writes the store and then runs both branches from
    it in the same process (`store_read.signal_in` waits for `store_write`). Keep
    `store_write.path`/`format` and `store_read.path`/`format` equal.
  - `fanout_from_store.json`: the same branches over `store_read` only (the second stage:
    `--outputs sink_a` and `--outputs sink_b` in two processes, or `--outputs materialize_read`
    to time reading the store alone).

  Other sizes and thread counts use `--set`, for example 5M rows in 64 partitions:
  `--set data.rows=5000000 --set data.npartitions=64` (plus `data2.rows`/`data2.npartitions` for
  joins, union and shared upstream, `data.key_cardinality=500000` for `groupby_key10*`);
  `--set materialize.num_workers=1` for one thread; `--set materialize.mode=checksum` to verify
  the result (`sorted_by` is already set in the sort scenarios).

  `DataFrameSortValues`, `DataFrameSetIndex`, `DataFrameQuery` and `DataFrameAddColumnByExpression`
  are `EXPERIMENTAL`: the node registry includes them only when `DEBUG` is on (the compose `.env`
  sets it; a host run needs `DEBUG=True`). `DataFrameSetIndex` is also tagged `Unstable` and
  `Not tested`, which are disabled when `ENVIRONMENT=prod`.

Node ids are the same for every database: `connection`, `ensure_table`, `data`, `write` in write
scenarios and `connection`, `read`, `groupby`, `materialize` in read scenarios. Use them in matrix
`node_overrides` and `--outputs`.

Read scenarios expect `bench_wide_5m` to be seeded first with `seed.py` (its defaults: 5 000 000
rows, 64 partitions, seed 42, `wide_mixed`). MSSQL scenarios use the `benchdb` database, which
neither the container nor the benchmark nodes create; pass `--create-database` to the seeder once.

Connection parameters are pipeline constants. `BenchmarkSqlConnection` expands `${VAR}` and
`${VAR:-default}` in them; the defaults match the host ports of `docker/docker-compose.tests.yaml`:

| Database | Variables (default) | Fixed values |
|---|---|---|
| PostgreSQL | `DVT_BENCH_PG_HOST` (`localhost`), `DVT_BENCH_PG_PORT` (`54321`), `DVT_BENCH_PG_PASSWORD` | database `testdb`, user `testuser` |
| ClickHouse | `DVT_BENCH_CH_HOST` (`localhost`), `DVT_BENCH_CH_PORT` (`8124`), `DVT_BENCH_CH_PASSWORD` | database `testdb`, user `testuser` |
| MSSQL | `DVT_BENCH_MSSQL_HOST` (`localhost`), `DVT_BENCH_MSSQL_PORT` (`11433`), `DVT_BENCH_MSSQL_DB` (`benchdb`), `DVT_BENCH_MSSQL_PASSWORD` | user `sa` |
| MySQL (write only) | `DVT_BENCH_MYSQL_HOST` (`localhost`), `DVT_BENCH_MYSQL_PORT` (`33061`), `DVT_BENCH_MYSQL_PASSWORD` | database `testdb`, user `testuser` |

Password defaults are the compose test passwords; set the variables for any other database.

Notes:

- Run from the repository root. A pipeline path that does not exist relative to the working
  directory falls back to the first file with the same basename under `pipelines/`. Files such as
  `append_1m.json` or `full_5m.json` exist for every database, so the fallback can silently pick
  another database. The same applies to pipeline paths inside matrix files.
- `--npartitions`, `--num-workers`, `--max-rows-per-partition`, `--preset` and matrix
  `parameters` override every node input with that name, including
  `BenchmarkSyntheticDataFrame.npartitions` and `BenchmarkMaterialize.num_workers`. Use
  `--set NODE.INPUT=VALUE` or matrix `node_overrides` to change one node; a matrix case wins over
  `--set` for the same input.
- Input overrides (global and per node) apply only to internal-format pipelines. A `ui_graph`
  pipeline is converted to `NodeData` objects before overrides are applied, and
  `apply_input_overrides` skips them without an error.
- ClickHouse uses HTTP. clickhouse-connect honours `HTTP_PROXY`/`HTTPS_PROXY` for `localhost`
  unless `NO_PROXY` lists it; behind a local proxy large inserts failed with `Empty query` or
  HTTP 503. Set `NO_PROXY=localhost,127.0.0.1` in that case.

Only input scenarios should live in `pipelines/`.
Run artifacts are written to `tmp/task_benchmarking/runs/<run_id>/`.

## Benchmark nodes

`services/task_benchmarking/nodes/` contains seven test nodes (category `Benchmark`, tag `Testing`,
`VISIBLE=False`). They are not part of `src/nodes` discovery: the runner registers them with
`register_benchmark_nodes()` before every run, so they exist only in the benchmark process.

- `BenchmarkSqlConnection` outputs `connection` (`SqlConnectionRecord`). Inputs:
  `connection_type` (`postgres`, `clickhouse`, `mssql`, `mysql`), `host`, `port`, `database`,
  `user`, `password`, `password_env`, `driver`, `driver_options`. It builds and validates an
  in-memory connection record, so no stored DVT connection is needed. `${VAR}` and
  `${VAR:-default}` are expanded in string inputs: `:-` also applies to an empty variable, and
  `${VAR}` without a default fails when the variable is unset. `password_env` names a variable
  that is read first; when it is unset, `password` is used. Default drivers: `psycopg`, `http`,
  `pyodbc` (`ODBC Driver 18 for SQL Server`, unencrypted) and `pymysql`. The node logs the type,
  driver, host, port, database and user, never the password.
- `BenchmarkEnsureTable` creates `table_name` (optionally in `db_schema`) with the DDL of the
  synthetic `schema` (`synthetic.create_table_sql`). `on_exists=recreate` (default) drops and
  recreates an existing table; `keep` leaves it as is. The database must already exist. Write
  scenarios link `write.signal_in` to `ensure_table.signal_out`, so the writer starts after the
  table is ready. Records `table_action` (`created`, `recreated` or `kept`).
- `BenchmarkSyntheticDataFrame` outputs `output` (`dd.DataFrame`). Inputs: `rows`,
  `npartitions` (16), `seed` (42), `schema` (`wide_mixed`, `numeric`, `wide_text` or `dim`),
  `key_cardinality` (0). The DataFrame is lazy (`dd.from_map` over `synthetic.partition_plan`): a
  partition is generated only when it is computed. The same `rows`, `npartitions`, `seed` and
  `schema` produce the same rows as `seed.py`. `key_cardinality > 0` appends an int64 `key`
  column with that many distinct values (see Schemas); the other columns stay the same.
  Records `rows`.
- `BenchmarkMaterialize` is an output node that forces computation of `df`. Inputs: `df`,
  `num_workers` (8), `mode`, `sorted_by`. `count_rows` (default) computes `len` of every partition
  and sums them without building a full frame; `full_pandas` collects one pandas DataFrame and also
  records `pandas_bytes` (`memory_usage(deep=True)`); `checksum` computes, per partition, every
  column's non-null `count` and a `sum` (exact integer sum for integers and booleans, float sum for
  floats, whole seconds since the epoch for datetimes, total value length for text), merges them
  into the `checksum` metric and, with `sorted_by`, records `sorted_ok` (each partition ascending
  by that column and partitions in order). Index values are not part of the checksum. `checksum`
  does more work per partition than `count_rows`, so time with `count_rows` and verify in
  separate runs. `num_workers <= 1` uses the dask `sync` scheduler, otherwise `threads`. Records
  `rows`, `mode` and `num_workers`.
- `BenchmarkMaterializeConcurrent` is an output node with two DataFrame inputs, `df` and `df_b`,
  computed in one `dask.compute` call on one thread pool, so the branches run concurrently and an
  upstream they share is computed once. Inputs `num_workers`, `mode` (`count_rows` or
  `checksum`), `sorted_by` (for `df`) and `sorted_by_b`. Records `rows` (sum of both),
  every `BenchmarkMaterialize` metric of each input with the suffix `_a` or `_b` (`rows_a`,
  `checksum_b`, ...), `mode` and `num_workers`.
- `BenchmarkStoreWrite` is an output node that emulates a stage barrier: it computes `df` and
  writes every partition to one file `part-<number>` in the directory `path` (created when
  missing; partition files left by an earlier run are deleted first, other files are kept).
  `format`: `parquet` (default; `compression` None is snappy), `arrow_ipc` (Arrow IPC file;
  None is uncompressed, `lz4`/`zstd` allowed) or `dvt_codec` (the bytes the pipeline cache puts
  into Valkey per partition: `DumpEngineCodec`, msgpack around Feather with lz4; `compression`
  is ignored). `parquet` and `arrow_ipc` drop the index. Inputs also `num_workers` (8). Records
  `rows`, `partitions`, `store_bytes` (file sizes), `frame_bytes` (in-memory size of the written
  partitions, deep), `write_s` (encode + write time summed over partitions, thread seconds,
  overlapping when `num_workers > 1`), `format`, `compression` and `num_workers`.
- `BenchmarkStoreRead` outputs a lazy `dd.DataFrame` with one partition per file of `path`
  in file order; `process()` reads the first file for the meta. Inputs `path`, `format`. Records
  `partitions` and `store_bytes`. Link its `signal_in` to the writer's `signal_out` when both are
  in one pipeline.

A definitions registry lookup of an unknown node name re-bootstraps the node registry in that
process and drops the benchmark nodes until the next `register_benchmark_nodes()` call.

## Metrics

Task level (`report.json` task report and the `report.txt` summary):

- `duration_s`: task wall time. Node registry bootstrap happens before the task starts and is not
  included.
- `rows_total`: sum of `rows` over output nodes (`OUTPUT_NODE=True`, for example
  `WriteDataFrameToDBV4` and `BenchmarkMaterialize`); `null` when no output node reported rows.
  Source rows are not added, so a read followed by a sink is not counted twice. It counts rows
  reaching the sink: `groupby_5m` reports the number of groups, not the rows read.
- `cpu_user_s`, `cpu_system_s`: CPU time of the whole benchmark process between task start and
  finish, all threads included, so the values can exceed `duration_s`.
- `cgroup_memory_peak_bytes`: `/sys/fs/cgroup/memory.peak` (cgroup v2) or
  `memory/memory.max_usage_in_bytes` (cgroup v1), read when the task finishes. It is the peak of
  the container since the cgroup was created, including earlier runs in the same container, and
  `null` outside a Linux container.

Node level (`nodes[]` in `report.json`, columns in `report.txt`):

- `metrics`: values a node recorded with `services.task_benchmarking.metrics.record_metric`.
  For nodes that emit the `rows_written` system variable (`WriteDataFrameToDBV4`), `rows` is
  taken from it.
- `duration_s`: from the node start callback to its success or error callback.
- `rows_per_s`: `metrics.rows / duration_s` when both are known, otherwise `null`.

DataFrame-producing nodes (`DFOutputBaseNode` subclasses such as `ReadTableFromDBV3` and
`BenchmarkSyntheticDataFrame`) only build a lazy graph in `process()`. Their callbacks fire while
the output partitions are computed by downstream nodes, so their `duration_s` overlaps the
consumer and is indicative only. Judge throughput by the sink node (`write`, `materialize`).

`env.txt` replaces the value of every variable whose name contains `PASSWORD`, `SECRET`, `TOKEN`,
`KEY` or `FERNET` (case-insensitive) with `***`.

## Local run

```bash
{venv_dir_path}\Scripts\python.exe -m services.task_benchmarking.main --pipeline services/task_benchmarking/pipelines/examples/sample_pipeline.json
```

Use a specific user ID when the pipeline depends on user-scoped connections:

```bash
{venv_dir_path}\Scripts\python.exe -m services.task_benchmarking.main --pipeline services/task_benchmarking/pipelines/examples/sample_pipeline.json --user-id <user-id>
```

## Compose run (dev + tests override)

`docker/docker-compose.tests.yaml` is applied on top of `docker/docker-compose.base.yaml` and
`docker/docker-compose.dev.yaml`; run the commands from the repository root with `--project-directory .`.

The `task_benchmarking` image is built like task-worker: same `additional_contexts`, and the runtime
base is `dvt/base-odbc`, so `pyodbc` with ODBC Driver 18 works for MSSQL. The container:

- joins the project default network (`postgres_test_db`, `mssql_test_db`) and `dvt-net` (`clickhouse_test_db`);
- gets `DVT_BENCH_*_HOST/PORT` pointing at those services;
- is limited to `${DVT_BENCH_MEM_LIMIT:-8g}` of memory (`mem_limit`).

Build the image and start the test databases:

```bash
docker compose --project-directory . -f docker/docker-compose.base.yaml -f docker/docker-compose.dev.yaml -f docker/docker-compose.tests.yaml build task_benchmarking
docker compose --project-directory . -f docker/docker-compose.base.yaml -f docker/docker-compose.dev.yaml -f docker/docker-compose.tests.yaml up -d postgres_test_db clickhouse_test_db mssql_test_db
```

Run a one-shot benchmark (artifacts land in `./tmp/task_benchmarking/runs` through the `./tmp` bind mount):

```bash
docker compose --project-directory . -f docker/docker-compose.base.yaml -f docker/docker-compose.dev.yaml -f docker/docker-compose.tests.yaml run --rm task_benchmarking --pipeline /app/services/task_benchmarking/pipelines/examples/sample_pipeline.json
```

Seed from inside the container (internal ports, no host proxy involved):

```bash
docker compose --project-directory . -f docker/docker-compose.base.yaml -f docker/docker-compose.dev.yaml -f docker/docker-compose.tests.yaml run --rm --entrypoint python3 task_benchmarking -m services.task_benchmarking.seed --db mssql --rows 5000000 --table bench_wide_5m --create-database
```

Set `DVT_BENCH_MEM_LIMIT` (for example `16g`) to change the container memory limit.

## Seeding test databases

`seed.py` loads deterministic synthetic rows from `synthetic.py` into the compose test databases
through each driver's fastest bulk path. The same `--rows`, `--npartitions`, `--seed` and `--schema`
reproduce exactly the data that benchmark nodes generate in memory (a partition's content depends on
its size, so keep `--npartitions` equal). The reported rate is the "native write ceiling" reference
for each database.

| `--db` | Load path | `--batch-rows` default |
|---|---|---|
| `postgres` | psycopg 3 `COPY ... FROM STDIN (FORMAT csv)`, CSV encoded by Arrow, one transaction per partition | 100000 rows per COPY chunk |
| `clickhouse` | clickhouse-connect `insert_arrow` (`--ch-insert df` uses `insert_df`); partitions are grouped into blocks | at least 500000 rows per insert |
| `mssql` | pyodbc `fast_executemany` (ODBC Driver 18), one commit per partition | 50000 rows per `executemany` |

Seed from the host venv. Defaults are `localhost`, the published test ports `54321` / `8124` / `11433`,
the compose test credentials, database `testdb` for PostgreSQL/ClickHouse and `benchdb` for MSSQL
(`mssql_test_db` has only `SA`; `--create-database` creates `benchdb`):

```bash
{venv_dir_path}\Scripts\python.exe -m services.task_benchmarking.seed --db postgres --rows 1000000 --table bench_wide_1m
{venv_dir_path}\Scripts\python.exe -m services.task_benchmarking.seed --db clickhouse --rows 5000000 --table bench_wide_5m
{venv_dir_path}\Scripts\python.exe -m services.task_benchmarking.seed --db mssql --rows 5000000 --table bench_wide_5m --create-database
```

- Seeding is idempotent: when the table already holds `--rows` rows the command prints `already seeded`
  and exits 0; `--recreate` forces drop + reload.
- `--dry-run` prints the plan and DDL without connecting.
- Connection values resolve as CLI flag, then `DVT_BENCH_<PG|CH|MSSQL>_<HOST|PORT|USER|PASSWORD|DATABASE>`,
  then the default; `--password-env VAR` reads the password from another variable. Passwords are never printed.
- If `HTTP_PROXY` is set, clickhouse-connect routes ClickHouse traffic through it and inserts can fail
  with `Empty query` or HTTP 503; set `NO_PROXY=localhost,127.0.0.1` for host runs (the seeder warns
  when this applies).

The run ends with:

```text
seeded 5000000 rows into postgres.bench_wide_5m in 15.10 s (331035 rows/s, batch=100000)
timing: generate+encode=8.37 s (overlapped with load), load=14.92 s
verify: COUNT(*) FROM testdb.bench_wide_5m = 5000000 (ok)
```

Schemas (column types per dialect live in `synthetic.SCHEMA_COLUMNS`):

- `wide_mixed` (13 columns, about 200 B/row in the PostgreSQL heap): `id` int64 PK, `int_a` int32,
  `int_b` nullable Int64 (5% NULL), `float_a`, `float_b`, `amount` (2 decimals, `NUMERIC/Decimal(18,2)`),
  `str_low` (`group_00`..`group_19`), `str_high` (16 random chars), `str_text` (64 random chars),
  `str_null` (16 chars, 10% NULL), `bool_a`, `ts_a` (millisecond precision, 2020-2025), `date_a`.
- `numeric`: `id`, `value`.
- `dim` (lookup table for joins): `id`, `dim_label` (12 random chars), `dim_weight` (`[0, 1)`).
- `key` (any schema, `key_cardinality = K > 0`): `id * 2654435761 % K`. Rows `0..N-1` give every
  value `N // K` or `N // K + 1` times, and every partition holds `min(K, partition rows)` distinct
  keys, so a group-by or join on `key` touches every partition.
- `wide_text` (5 columns, about 8.2 KB/row): `id` int64 PK and `text_a`..`text_d`, 2048 random ASCII
  chars each (`TEXT`, ClickHouse `String`, SQL Server `NVARCHAR(MAX)`). `text_a`/`text_b` are pandas
  strings and `text_c`/`text_d` stay object columns of Python strings, as in a frame whose columns
  were not converted.

## Docker image run

Build:

```bash
docker build -f services/task_benchmarking/docker/dev.Dockerfile -t dvt/memory-benchmark:dev .
```

Run:

```bash
docker run --rm -v "${PWD}/services/task_benchmarking/pipelines/examples/sample_pipeline.json:/data/pipeline.json" dvt/memory-benchmark:dev --pipeline /data/pipeline.json
```

## Artifacts

Each run writes structured artifacts into:

```text
tmp/task_benchmarking/runs/<run_id>/
  config.json
  report.txt
  report.json
  env.txt
```

Default output root is `tmp/task_benchmarking/runs` and can be overridden with `--output-root`.

## Options

- `--report <path>`: explicit path for text report (`report.txt` by default).
- `--report-json <path>`: explicit path for JSON report (`report.json` by default).
- `--output-root <path>`: root folder for run artifacts (default: `tmp/task_benchmarking/runs`).
- `--run-id <id>`: explicit run id; otherwise generated as `<timestamp>_<pipeline-name>`.
- `--pipeline-format <auto|internal|ui_graph>`: explicit input format.
- `--exec-mode <full|metadata_only>`: execute the full pipeline or only node metadata lifecycle.
- `--validate-only`: validate pipeline + options without executing nodes.
- `--dry-run`: resolve effective pipeline/options and artifact paths without execution.
- `--preset <ram_8g|ram_16g>`: apply memory-safety preset for common tuning inputs.
- `--npartitions <int>`, `--num-workers <int>`, `--max-rows-per-partition <int>`: CLI control for key performance/memory inputs.
- `--outputs <node_id> [node_id ...]`: run only selected nodes.
- `--set NODE.INPUT=VALUE` (repeatable): override one input of one node; VALUE is parsed as JSON,
  otherwise kept as a string. Like matrix `node_overrides`, it applies only to inputs present in
  the pipeline file.
- `--sample-interval <seconds>`: RSS sampling interval (default: `0.1`).
- `--repeat <n>`: run multiple times in one process to detect leaks.
- `--repeat-include-reports`: include full per-run reports in stdout for repeat mode.
- `--include-metadata`: include per-node output metadata in human/LLM formats.

Every JSON report includes compact `metadata_metrics` per node: UTF-8 payload bytes and counts of
database, schema, table, and column objects. Use `--exec-mode metadata_only --repeat 10` for DB
metadata latency comparisons without executing the data path.
- `--user-id <user-id>`: override `task.user_id` (or set `TASK_BENCHMARKING_USER_ID`).
- `--matrix <file.json|file.yaml>`: run matrix of scenarios.
- `--compare-candidate-python <python.exe>` (+ optional `--compare-candidate-workdir`, `--compare-candidate-pipeline`): safe compare baseline vs candidate without mutating git state.
- `--patch <file.patch>`: legacy unsafe compare via `git apply` (mutates git state).

JSON report schema files:

- `services/task_benchmarking/schemas/benchmark_report.schema.json`
- `services/task_benchmarking/schemas/benchmark_run.schema.json`

## Safe compare workflow (recommended)

Safe compare runs baseline and candidate as separate subprocesses and does not call `git apply`.

Example:

```bash
{venv_dir_path}\Scripts\python.exe -m services.task_benchmarking.main \
  --pipeline services/task_benchmarking/pipelines/benchmarks/read/postgres/full_5m.json \
  --compare-candidate-python C:\work\projects\Visual_transformer_candidate\{venv_dir_path}\Scripts\python.exe \
  --compare-candidate-workdir C:\work\projects\Visual_transformer_candidate \
  --preset ram_8g
```

Summary is written to `tmp/task_benchmarking/runs/<run_id>/compare_report.json`.

## Patch workflow (legacy, unsafe)

When patch files are provided, the service runs baseline first, then applies patches with `git apply`,
runs patched code, and finally reverts patches with `git apply --reverse`.

Patch mode mutates git state and is unsafe in a dirty repository. Prefer safe compare mode above.

Example:

```bash
{venv_dir_path}\Scripts\python.exe -m services.task_benchmarking.main --pipeline services/task_benchmarking/pipelines/examples/sample_pipeline.json --patch C:\tmp\optimizations.patch
```

## Matrix workflow

Matrix config supports `pipelines`, cartesian `parameters`, and explicit `cases`.

Example matrix config:

```yaml
pipelines:
  - path: services/task_benchmarking/pipelines/benchmarks/read/postgres/full_5m.json
    name: read-pg-full-5m
parameters:
  npartitions: [16, 64, 256]
```

Run:

```bash
{venv_dir_path}\Scripts\python.exe -m services.task_benchmarking.main \
  --pipeline services/task_benchmarking/pipelines/benchmarks/read/postgres/full_5m.json \
  --matrix services/task_benchmarking/pipelines/benchmarks/matrix/read_npartitions.yaml \
  --preset ram_8g
```

Matrix summary is written to `tmp/task_benchmarking/runs/<matrix_run_id>/matrix_report.json`.

## LLM experiment workflow

Important: `experiments/` is reserved for experiment reports only.

1. Review existing reports in `experiments/`.
2. Implement changes in the repository.
3. Export diff as patch file.
4. Run memory benchmark with `--patch`.
5. Evaluate result.
6. Save report in `experiments/` as `YYYY-MM-DDTHH-MM-SS_short-name.md` with summary, details, and outcome.
