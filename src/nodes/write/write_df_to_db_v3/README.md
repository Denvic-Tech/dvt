# WriteDataFrameToDBV3

Node type: `WriteDataFrameToDBV3`.

## Purpose and selection

Write a DataFrame into an existing SQL table by matching column names. For explicit source-to-target column mapping, choose WriteDataFrameToDBV4.

## Inputs and configuration

Connect a SQL connection object to `connection` and a DataFrame to `df`. Set `table_name` and, where needed, `schema_name`/`database_name`. `write_mode` defaults to `append`; `truncate` clears the target before insertion; `upsert` requires `upsert_config` with one key. `chunksize` (rows per INSERT) is empty by default and then follows the database type: 100000 for ClickHouse, 1000 for other databases; an instance an operator switched back to the legacy policy uses 1000 everywhere. An explicit value always wins; memory per chunk grows with it. Extra DataFrame columns default to `on_extra_df_columns=ignore`. Missing target columns default to `on_missing_df_columns=ignore_if_default`; `ignore` omits them without the same default check, while `error` rejects them.

## Outputs

No DataFrame output. System variables `target_table` and `rows_written` report the writer's target and count.

## Behavior and limitations

The database, schema and table must already exist; this node does not infer or create them. Internal DVT columns are removed. Null values in present columns remain values; omitting a column is different and can allow a database default. Target constraints still apply. Data is computed and written in batches/partitions; stages can commit separately, so failure need not roll back the whole run. Append can duplicate data on rerun; truncate removes existing rows; upsert support and SQL behavior depend on the target dialect.

Partitions are written by parallel worker threads. A positive project worker count sets their number; otherwise the instance uses a default per database type, which an operator can override or switch back to one fixed count for all databases. An instance-wide upper limit always applies. The same threads also compute the upstream partitions of `df`, including source database reads. More threads are not always faster: drivers such as psycopg and pyodbc can slow down under thread contention, while ClickHouse can gain.

ClickHouse inserts are synchronous: an INSERT returns once its rows are in a table part, so all rows are visible when the node finishes, and earlier chunks are visible while it runs. Each INSERT creates at least one part per table partition. Many small INSERTs keep the server merging and can fail with "Too many parts" once a partition exceeds the table setting `parts_to_throw_insert`. ClickHouse recommends about one INSERT per second per table, in large batches, hence the 100000-row default. For many small, frequent writes V4 offers an opt-in `async_insert`. The node uses the ClickHouse HTTP interface: a connection with the native driver on the default native port (9000, or 9440 with TLS) is redirected to the default HTTP port (8123 or 8443) with a warning in the log, and a native connection on any other port fails with an error asking for the http driver and the server HTTP port.

## Examples

Assume an existing table orders(id INTEGER, amount INTEGER) and input rows (1,10), (2,20). Connect the connection object's output to `connection` and the frame to `df`:

```json
{
  "table_name": "orders",
  "write_mode": "append",
  "on_extra_df_columns": "error",
  "on_missing_df_columns": "error",
  "chunksize": 1000
}
```

Two rows are appended if constraints permit; rows_written reports 2. Existing rows remain.

## Common errors

Missing table: create and inspect it first. Different source/target names: rename columns upstream or use V4 mapping. A missing required target column needs data or a valid database default/policy. Type, nullability and unique-key failures require aligning input with the existing target. Check partial writes before retrying.
