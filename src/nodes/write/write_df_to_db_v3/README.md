# WriteDataFrameToDBV3

Node type: `WriteDataFrameToDBV3`.

## Purpose and selection

Write a DataFrame into an existing SQL table by matching column names. For explicit source-to-target column mapping, choose WriteDataFrameToDBV4.

## Inputs and configuration

Connect a SQL connection object to `connection` and a DataFrame to `df`. Set `table_name` and, where needed, `schema_name`/`database_name`. `write_mode` defaults to `append`; `truncate` clears the target before insertion; `upsert` requires `upsert_config` with one key. `chunksize=1000`. Extra DataFrame columns default to `on_extra_df_columns=ignore`. Missing target columns default to `on_missing_df_columns=ignore_if_default`; `ignore` omits them without the same default check, while `error` rejects them.

## Outputs

No DataFrame output. System variables `target_table` and `rows_written` report the writer's target and count.

## Behavior and limitations

The database, schema and table must already exist; this node does not infer or create them. Internal DVT columns are removed. Null values in present columns remain values; omitting a column is different and can allow a database default. Target constraints still apply. Data is computed and written in batches/partitions; stages can commit separately, so failure need not roll back the whole run. Append can duplicate data on rerun; truncate removes existing rows; upsert support and SQL behavior depend on the target dialect.

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
