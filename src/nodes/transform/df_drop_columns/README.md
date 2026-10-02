# DataFrameDropColumns

Node type: `DataFrameDropColumns`.

## Purpose and selection

Remove unwanted DataFrame columns. Prefer this when the columns to discard are known; use `DataFrameSelectColumns` for an explicit retained list.

## Inputs and configuration

Connect a DataFrame to `df`; set `columns` to exact names to remove.

## Outputs

`output` contains the remaining columns and rows.

## Behavior and limitations

Missing names are ignored. If a dropped business column also names the physical index, the index is retained but renamed to an internal DVT name; its divisions remain available. This removes a field, not rows or duplicates.

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
