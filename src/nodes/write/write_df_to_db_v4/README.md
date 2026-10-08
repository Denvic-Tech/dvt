# Write DataFrame to DB V4

## Purpose and selection

`WriteDataFrameToDBV4` writes a DataFrame into an existing database table. Use it for controlled append, full replacement or key-based replacement. It never creates the target database, schema or table; prepare and inspect the target first.

## Inputs and configuration

Connect a DataFrame to `df` and `GetExistDBConnection.connection` to `connection`. Set `table_name`, optional `database_name` and `schema_name`. `write_mode` defaults to `append`; `truncate` replaces all rows; `upsert` requires `upsert_config={"key_column":"id"}` using the target key name. Supply `upsert_config` only for upsert. `column_mapping` contains `source_name` / `target_name` pairs, with optional `dtype` / `nullable`. `on_extra_df_columns` defaults to `ignore`; `on_missing_df_columns` defaults to `ignore_if_default`. `chunksize` defaults to 1000.

Through MCP, inspect the exact target and known input schema before configuring the writer. Call `resolve_write_columns` on initial setup or schema changes: `typed_create` for a missing table, `existing_table` otherwise. Prepare missing objects with `create_database`, `create_schema`, `create_table`; create_table never alters an existing table. For column changes use `apply_table_column_actions`: preview each batch with `dry_run=true` (default), review SQL/diagnostics, then apply the same batch with `dry_run=false`. Reread `get_database_table`, resolve again after changes and set explicit `column_mapping`. Unchanged configured pipelines need no repeated resolution for every run. One-time MCP preparation needs no DDL node or signal edge; runtime DDL or unsupported MCP operations may use a justified specialized/SQL node with the appropriate dependency.

Suggested actions are recommendations, not authorization. Drop/recreate require explicitly agreed data loss; `recreate_column` drops and adds a column and does not preserve its values. Preview does not scan existing NULLs; apply checks them before `nullable=false`. Pause concurrent ClickHouse writes for that change. After failure/timeout inspect actual state before planning remaining actions. Preview alone requires no additional user confirmation. For comment removal supply explicit `comment: null`; for `set_column_nullable` provide a boolean and omit column/comment fields. During preview, `applied_actions` describes planned actions, not executed DDL.

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
