# DataFrameSelectColumns

Node type: `DataFrameSelectColumns`.

## Purpose and selection

Keep selected ordinary columns. Use `DataFrameDropColumns` when only the unwanted fields are known.

## Inputs and configuration

Connect `df` and provide a non-empty `columns` list in the desired order.

## Outputs

`output` contains the retained columns with the original index.

## Behavior and limitations

The implementation silently filters absent names and excludes a selected name equal to the index name, even if that name also exists as a column. It preserves the physical index. An empty configured list returns before assigning `output`; it is not an all-columns shortcut. If every requested name is filtered out, the result can have no ordinary columns.

## Examples

The input has `id, amount, region` and an unnamed index.

Parameter values (without an MCP patch envelope):

```json
{
  "columns": [
    "amount",
    "region"
  ]
}
```

The output ordinary columns are `amount, region`, in that order.

## Common errors

Missing result: do not pass an empty list. Missing field: inspect both input columns and the index name. Recheck output metadata before configuring a consumer.
