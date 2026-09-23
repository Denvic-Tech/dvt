# DataFrameUnpivot

Node type: `DataFrameUnpivot`.

## Purpose and selection

Turn several measurement columns into name/value rows. Use `DataFramePivot` for the reverse layout.

## Inputs and configuration

Connect `df`. `index_columns` identifies fields to keep; `columns_to_long` selects measurement columns, or omit it for all non-identifiers. Output names default to `variable` and `value` via `new_column_name_with_names` and `new_column_name_with_values`.

## Outputs

`output` repeats identifiers for each melted field and adds the name/value columns.

## Behavior and limitations

Both new columns are converted to strings for non-null entries; missing entries become None. Numeric measurement types are therefore not retained. Identifier fields existing only in a named index are reset into columns. Row count grows with the number of melted fields.

## Examples

Input has one row `id=1, jan=10, feb=20`.

Parameter values, without an MCP patch envelope:

```json
{
  "index_columns": [
    "id"
  ],
  "columns_to_long": [
    "jan",
    "feb"
  ]
}
```

Output has two rows: `(1, jan, "10")` and `(1, feb, "20")`.

## Common errors

Missing field: verify metadata. Name collisions: choose unused output names. Cast the value column after unpivot if numeric aggregation is required.
