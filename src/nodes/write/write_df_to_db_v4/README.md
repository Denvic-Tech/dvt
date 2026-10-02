# Write DataFrame to DB V4

## Purpose and selection

`WriteDataFrameToDBV4` writes a DataFrame into an existing database table. Use it for controlled append, full replacement or key-based replacement. It never creates the target database, schema or table; prepare and inspect the target first.

## Inputs and configuration

Connect a DataFrame to `df` and `GetExistDBConnection.connection` to `connection`. Set `table_name`, optional `database_name` and `schema_name`. `write_mode` defaults to `append`; `truncate` replaces all rows; `upsert` requires `upsert_config={"key_column":"id"}` using the target key name. Supply `upsert_config` only for upsert. `column_mapping` contains `source_name` / `target_name` pairs, with optional `dtype` / `nullable`. `on_extra_df_columns` defaults to `ignore`; `on_missing_df_columns` defaults to `ignore_if_default`. `chunksize` defaults to 1000.

Through MCP, inspect the target with `get_database_table` before applying or running the graph. Prepare missing objects with `create_database`, `create_schema` or `create_table` using the intended DataFrame metadata and target constraints, then inspect the target again. Input `agent_description` metadata explains target preparation and write-mode decisions.

## Outputs

This is a sink: there is no DataFrame result port. System variables `target_table` and `rows_written` describe the completed write. `rows_written` counts inserted input rows, not the final table size.

## Behavior and limitations

Internal DVT columns are removed. Mapping does not alter the target schema. Missing columns remain subject to target defaults/nullability and the chosen policy. Upsert uses one key column, stages input, removes matching target rows and inserts staged rows; it is not a partial update of selected fields. It does not deduplicate input. Truncate/upsert need temporary-table permissions and dialect support. Writes may use separate transactions for chunks and stages; do not assume whole-run atomicity. Repeating append can duplicate data; a failed write can have partial effects.

## Examples

Assume `public.order_totals(id, total)` already exists with compatible types. Connect the DB object and a DataFrame with `id, amount`.

```json
{"table_name":"order_totals","schema_name":"public","write_mode":"append","column_mapping":[{"source_name":"id","target_name":"id"},{"source_name":"amount","target_name":"total"}],"on_extra_df_columns":"error"}
```

Parameter values only. Two input rows append two rows. To replace rows with matching `id`, use `write_mode="upsert"` and `upsert_config={"key_column":"id"}` after verifying the intended key and input uniqueness.

## Common errors

Missing target: create it separately and inspect it again. Duplicate mapping targets, incompatible types or forbidden nulls: fix the mapping/data against the actual table. Missing upsert key/config: supply the target key. After a failed write, inspect the target before retrying. Use truncate only for an intended full replacement.
