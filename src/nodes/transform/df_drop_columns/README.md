# DataFrameDropColumns

Node type: `DataFrameDropColumns`.

## Purpose and selection

Remove unwanted DataFrame columns. Prefer this when the columns to discard are known; use `DataFrameSelectColumns` for an explicit retained list.

## Inputs and configuration

Connect a DataFrame to `df`; set `columns` to exact names to remove.

## Outputs

`output` contains the remaining columns and rows.

## Behavior and limitations

Missing names are ignored. Dropping a column also clears its binding to a DBV3 index. If a legacy business index shares the dropped field's name, the index takes an internal DVT name and retains its divisions.

## Examples

Input `df` has `id, amount, debug`.

Parameter values (without an MCP patch envelope):

```json
{
  "columns": [
    "debug"
  ]
}
```

The output has `id, amount`.

## Common errors

An unchanged result often means a spelling/case mismatch; missing names do not raise an error. Check downstream references to removed fields.
