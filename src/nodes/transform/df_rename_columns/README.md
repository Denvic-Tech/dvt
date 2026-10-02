# DataFrameRenameColumns

Node type: `DataFrameRenameColumns`.

## Purpose and selection

Rename fields without changing their values. Use before joins or writes to align names.

## Inputs and configuration

Connect `df`; set `mapping` to an object of old-name → new-name pairs. Its default is null.

## Outputs

`output` contains renamed columns; other columns and rows remain.

## Behavior and limitations

Null mapping passes through the original DataFrame. A matching index name is renamed too, preserving the physical index. Mapping an absent column does not create it. Duplicate destination names are not resolved automatically.

## Examples

Connect a DataFrame with `customer_id, amount`.

Parameter values (without an MCP patch envelope):

```json
{
  "mapping": {
    "customer_id": "id"
  }
}
```

The output fields are `id, amount`.

## Common errors

If a name stays unchanged, verify the source spelling. Choose unique destination names and update downstream key/column settings.
