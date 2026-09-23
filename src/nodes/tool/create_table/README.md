# CreateTable

Node type: `CreateTable`.

## Purpose and selection

Create a database table from DataFrameMetadata before a writer runs. This is a DDL operation, not data insertion.

## Inputs and configuration

Connect a DB object to `connection`. Set `table_name`, optional database_name/schema_name and non-empty `dataframe_metadata.columns`. Optional `table_create_spec` supplies dialect-specific table/key options; consult its live schema. `on_exists` is error by default, or ignore/recreate.

## Outputs

`signal_out` indicates completion; system variables are target_table_name, target_schema_name, target_db_name. There is no DataFrame result.

## Behavior and limitations

Ignore leaves an existing table unchanged without reconciling its schema. Recreate drops the existing table and data before creating the replacement; later failure can leave it absent. Type/name/nullability normalization follows the database dialect, so inspect the resulting table. Metadata mode emits the signal/variables without executing DDL. DataFrameMetadata is a transport schema distinct from the TableSchema output of ConvertToSchema.

## Examples

In an existing database/schema with DDL permission and no order_ids table, this creates an empty table. Connect signal_out → writer.signal_in to enforce order, then verify the target catalog before writing.

Parameter values, without an MCP patch envelope:

```json
{
  "table_name": "order_ids",
  "on_exists": "error",
  "dataframe_metadata": {
    "columns": [
      {
        "name": "id",
        "dtype": "INT",
        "nullable": false
      }
    ]
  }
}
```

## Common errors

Already exists: choose the intended on_exists policy, avoiding unintended recreate. Empty metadata is invalid. Missing schema/database or insufficient DDL rights must be resolved separately.
