# Read Table DB V3

## Purpose and selection

`ReadTableFromDBV3` reads a database table into a partitioned DataFrame. Prefer it for ordinary table extraction, followed by specialized filtering, projection, join or aggregation nodes. Choose `ReadQueryFromDBV3` when source-side SQL is necessary.

## Inputs and configuration

Connect `GetExistDBConnection.connection` → `connection`; the port takes an object, not an ID. Set `table_name`, and `database_name` / `schema_name` where applicable. Inspect the table catalog first and supply an explicit non-empty `columns` list; to read all columns, list every catalog column. Set `partition_col` to an exact raw column name, without SQL quoting, and choose a stable non-null scalar column. `partition_grouping`, `npartitions` and `max_rows_per_partition` tune extraction partitioning. `limit` bounds the requested read. `TTL_CACHE` defaults to 0. `time_zone` is exposed but is not applied by this node's current read path.

Input definitions expose concise localized UI descriptions and separate, non-localized `agent_description` guidance. Read that guidance before choosing fields; the profiling workflow below applies even when partition settings are omitted.

## Outputs

`output` is a Dask DataFrame. Output metadata preserves available source table and column comments. System variables are `source_table_name`, `source_schema_name`, `source_db_name`; pass variables through the standard variable ports.

## Behavior and limitations

Partition grouping controls physical reading, not business aggregation. Do not infer a guaranteed row order from partitioning. Metadata-only execution builds an empty DataFrame from reflected metadata; it does not prove that the full read succeeds. Unresolved target variables can leave metadata empty. Source comments are descriptive context. A persisted graph must not use a null `columns` entry as shorthand for all columns: null in an MCP input update removes that saved input.

`npartitions` is a target partition count; if omitted, the planner estimates it from row count, row width and instance settings. Without explicit grouping, orderable non-null keys use ranges; nullable or non-orderable keys use hash buckets. Explicit `{"mode":"range"}` rejects null keys; `{"mode":"hash","buckets":8}` requests hash buckets. `max_rows_per_partition` is a per-segment safety ceiling: exceeding it fails the read rather than splitting that segment automatically. Skewed keys can therefore fail even with many partitions. A key can also become the DataFrame index; selected key columns remain in the data. Each segment is read separately; do not assume a consistent snapshot of a changing source across those reads.

## Choosing partitions before building a graph

For each new or reconfigured read, inspect the table catalog and assess the source data through `query_database_readonly` (or reuse a recent profile of the same source and read scope). Estimate row count and the width of the selected columns. Check candidate key types, indexes, nulls, cardinality and skew. Prefer available source statistics and small aggregate results; use exact counts and distribution queries when affordable. `max_rows` limits the returned result, not the work performed by the database. A small preview alone cannot establish table size or rule out nulls and skew. Mark estimates and sampling uncertainty explicitly. A filter node after this reader does not reduce the source data fetched.

Choose and record a reading policy:

- **Verified small read:** for example, about 1,000 ordinary narrow rows can use `npartitions=1` without custom grouping or hash buckets. The current planner still needs a partition key. Check expected growth before fixing a recurring read to one partition.
- **Automatic sizing:** normally omit `npartitions` and let the planner estimate the count from rows, selected row width and instance settings. Omitting `partition_grouping` deliberately selects automatic range/hash choice; it does not replace profiling. Tens or hundreds of thousands of rows alone do not determine a useful partition count.
- **Explicit strategy:** `{"mode":"range"}` needs an orderable key without nulls. `{"mode":"hash"}` can handle supported nullable/non-orderable keys with an automatically sized bucket count; add `buckets` only when justified. Hashing cannot spread identical values or a large null group across buckets. A primary key or date column is a candidate, not a sufficient reason to choose it.
- **Temporal grouping:** before choosing year, month or day granularity, inspect counts per candidate period, especially the largest period. A date column or a business reporting period alone does not justify temporal read groups. Custom groups determine segments independently of the target count; `npartitions=1` does not override multi-period grouping or explicit hash buckets.

In the reader comment, summarize the evidence (measured or estimated), selected key, grouping decision, partition count policy and reason. If profiling is unavailable or times out, state the unknowns and use automatic sizing with a verified compatible key when feasible; do not assert optimality or force a single partition without evidence. Review available execution partition/memory diagnostics after the run. `max_rows_per_partition` is a failure guard, not a way to split an oversized group.

## Examples

Assume PostgreSQL `public.orders` has non-null integer `id` and numeric `amount`. Connect the DB connection object.

```json
{"table_name":"orders","schema_name":"public","columns":["id","amount"],"partition_col":"id"}
```

Parameter values only. This example deliberately keeps automatic sizing and range/hash selection after profiling. For the same source verified to contain about 1,000 narrow rows with no expected substantial growth, add `"npartitions":1` to read one partition. The output contains the selected table columns. For a verified datetime partition column with measured period sizes, a grouping value such as `{"mode":"granularity","granularity":"year"}` requests yearly read groups, not yearly totals.

## Common errors

Missing table/column: re-read the catalog and check database, schema, case and permissions. Partition errors: use the raw column name and a grouping compatible with its type. Excessive partitions: review distribution and partition settings rather than combining arbitrary overrides.
