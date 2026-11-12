# Task Benchmarking Service

Runs a pipeline from JSON and reports process RSS usage plus execution time overall and per node.

## Pipeline files

Input scenarios are stored in `services/task_benchmarking/pipelines/`:

- `examples/sample_pipeline.json`: DB-free smoke run, 200 000 synthetic rows counted by
  `BenchmarkMaterialize`.
- `benchmarks/write/<postgres|clickhouse|mssql|mysql>/append_1m.json`, `append_5m.json`: synthetic
  `wide_mixed` rows (1M in 16 partitions, 5M in 64 partitions) appended by `WriteDataFrameToDBV4`
  (`chunksize=1000`, `sync_column_descriptions=false`) into `bench_write_wide`, which
  `BenchmarkEnsureTable` recreates before every run. The ClickHouse scenarios set
  `chunksize=null` (the node's database default: 100 000 rows per INSERT, 1000 under
  `DB_CONCURRENCY_POLICY=legacy`) and `async_insert=false`; matrix `node_overrides` such as
  `write.chunksize` or `write.async_insert` replace them. An override applies only to an input
  that is present in the pipeline file.
- `benchmarks/read/<postgres|clickhouse|mssql>/full_5m.json`: `ReadTableFromDBV3` of the seeded
  `bench_wide_5m` table (64 range partitions on `id`), rows counted per partition.
- `benchmarks/read/<db>/preview_full_5m.json`: the same read collected into one pandas DataFrame;
  needs RAM for the whole table.
- `benchmarks/read/<db>/groupby_5m.json`: the same read followed by `DataFrameGroupByAgg`
  (`sum(amount)` and `count(id)` by `str_low`).
- `benchmarks/matrix/write_chunksize.yaml` (`write.chunksize` 1000/20000/100000) and
  `benchmarks/matrix/read_npartitions.yaml` (`read.npartitions` 16/64/256), both on PostgreSQL.

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
  `BenchmarkSyntheticDataFrame.npartitions` and `BenchmarkMaterialize.num_workers`. Use matrix
  `node_overrides` to change one node.
- Input overrides (global and per node) apply only to internal-format pipelines. A `ui_graph`
  pipeline is converted to `NodeData` objects before overrides are applied, and
  `apply_input_overrides` skips them without an error.
- ClickHouse uses HTTP. clickhouse-connect honours `HTTP_PROXY`/`HTTPS_PROXY` for `localhost`
  unless `NO_PROXY` lists it; behind a local proxy large inserts failed with `Empty query` or
  HTTP 503. Set `NO_PROXY=localhost,127.0.0.1` in that case.

Only input scenarios should live in `pipelines/`.
Run artifacts are written to `tmp/task_benchmarking/runs/<run_id>/`.

## Benchmark nodes

`services/task_benchmarking/nodes/` contains four test nodes (category `Benchmark`, tag `Testing`,
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
  `npartitions` (16), `seed` (42), `schema` (`wide_mixed` or `numeric`). The DataFrame is lazy
  (`dd.from_map` over `synthetic.partition_plan`): a partition is generated only when it is
  computed. The same `rows`, `npartitions`, `seed` and `schema` produce the same rows as
  `seed.py`. Records `rows`.
- `BenchmarkMaterialize` is an output node that forces computation of `df`. Inputs: `df`,
  `num_workers` (8), `mode`. `count_rows` (default) computes `len` of every partition and sums
  them without building a full frame; `full_pandas` collects one pandas DataFrame and also records
  `pandas_bytes` (`memory_usage(deep=True)`). `num_workers <= 1` uses the dask `sync` scheduler,
  otherwise `threads`. Records `rows`, `mode` and `num_workers`.

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
