# Task Benchmarking Service

Runs a pipeline from JSON and reports process RSS usage plus execution time overall and per node.

## Pipeline files

Input scenarios are stored in `services/task_benchmarking/pipelines/`:

- `pipelines/examples/sample_pipeline.json`
- `pipelines/benchmarks/read/...`
- `pipelines/benchmarks/write/...`

Only input scenarios should live in `pipelines/`.
Run artifacts are written to `tmp/task_benchmarking/runs/<run_id>/`.

## Local run

```bash
{venv_dir_path}\Scripts\python.exe -m services.task_benchmarking.main --pipeline services/task_benchmarking/pipelines/examples/sample_pipeline.json
```

Use a specific user ID when the pipeline depends on user-scoped connections:

```bash
{venv_dir_path}\Scripts\python.exe -m services.task_benchmarking.main --pipeline services/task_benchmarking/pipelines/examples/sample_pipeline.json --user-id <user-id>
```

## Compose run (dev + tests override)

`docker-compose.tests.yaml` is intended to be used as an override on top of `docker-compose.dev.yaml`.
The effective config is merged left-to-right, so services/variables from `docker-compose.tests.yaml`
override the same keys from `docker-compose.dev.yaml`.

Bring up required test infra and benchmark service:

```bash
docker compose -f docker-compose.dev.yaml -f docker-compose.tests.yaml up -d clickhouse_test_db task_benchmarking
```

Run a one-shot benchmark in compose:

```bash
docker compose -f docker-compose.dev.yaml -f docker-compose.tests.yaml run --rm task_benchmarking --pipeline /app/services/task_benchmarking/pipelines/examples/sample_pipeline.json
```

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
  --pipeline services/task_benchmarking/pipelines/benchmarks/read/clickhouse/read_v3_groupby.json \
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
  - path: services/task_benchmarking/pipelines/benchmarks/read/clickhouse/read_v3_groupby.json
    name: read-v3
parameters:
  npartitions: [32, 64]
  num_workers: [1, 2]
  max_rows_per_partition: [1000000]
```

Run:

```bash
{venv_dir_path}\Scripts\python.exe -m services.task_benchmarking.main \
  --pipeline services/task_benchmarking/pipelines/benchmarks/read/clickhouse/read_v3_groupby.json \
  --matrix tmp/memory_benchmark_matrix.yaml \
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
