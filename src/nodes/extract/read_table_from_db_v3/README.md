# Read Table DB V3

## Purpose and selection

`ReadTableFromDBV3` reads a database table into a partitioned DataFrame. Prefer it for ordinary table extraction, followed by specialized filtering, projection, join or aggregation nodes. Choose `ReadQueryFromDBV3` when source-side SQL is necessary.

## Inputs and configuration

Connect `GetExistDBConnection.connection` → `connection`; the port takes an object, not an ID. Set `table_name`, and `database_name` / `schema_name` where applicable. Inspect the table catalog first and supply an explicit non-empty `columns` list; to read all columns, list every catalog column. Set `partition_col` to an exact raw column name, without SQL quoting, and choose a stable non-null scalar column. `partition_grouping`, `npartitions` and `max_rows_per_partition` tune extraction partitioning. `limit` bounds the requested read. `TTL_CACHE` defaults to 0. `time_zone` is exposed but is not applied by this node's current read path.

## Outputs

`output` is a Dask DataFrame. Output metadata preserves available source table and column comments. System variables are `source_table_name`, `source_schema_name`, `source_db_name`; pass variables through the standard variable ports.

## Behavior and limitations

Partition grouping controls physical reading, not business aggregation. Do not infer a guaranteed row order from partitioning. Metadata-only execution builds an empty DataFrame from reflected metadata; it does not prove that the full read succeeds. Unresolved target variables can leave metadata empty. Source comments are descriptive context. A persisted graph must not use a null `columns` entry as shorthand for all columns: null in an MCP input update removes that saved input.

`npartitions` is a target partition count; if omitted, the planner estimates it from row count, row width and instance settings. Without explicit grouping, orderable non-null keys use ranges; nullable or non-orderable keys use hash buckets. Explicit `{"mode":"range"}` rejects null keys; `{"mode":"hash","buckets":8}` requests hash buckets. `max_rows_per_partition` is a per-segment safety ceiling: exceeding it fails the read rather than splitting that segment automatically. Skewed keys can therefore fail even with many partitions. A key can also become the DataFrame index; selected key columns remain in the data. Each segment is read separately; do not assume a consistent snapshot of a changing source across those reads.

## Examples

Assume PostgreSQL `public.orders` has non-null integer `id` and numeric `amount`. Connect the DB connection object.

```json
{"table_name":"orders","schema_name":"public","columns":["id","amount"],"partition_col":"id"}
```

Parameter values only. The output contains the selected table columns. For a verified datetime partition column, a grouping value such as `{"mode":"granularity","granularity":"year"}` requests yearly read groups, not yearly totals.

## Common errors

Missing table/column: re-read the catalog and check database, schema, case and permissions. Partition errors: use the raw column name and a grouping compatible with its type. Excessive partitions: review distribution and partition settings rather than combining arbitrary overrides.
