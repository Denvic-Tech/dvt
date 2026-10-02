# DataFrameFillNA

Node type: `DataFrameFillNA`.

## Purpose and selection

Fill missing values using a statistic or directional propagation. This node's mapping contains function names, not literal replacement values.

## Inputs and configuration

Connect `df`; supply a non-empty `fill_values` object: column → `mean`, `median`, `mode`, `min`, `max`, `ffill` or `bfill`.

## Outputs

`output` preserves columns and fills missing entries in configured fields.

## Behavior and limitations

Statistics operate on the selected series; `mode` chooses the value with maximum frequency. Ties have no node-specific business rule. Directional fills depend on row/partition order; the node does not sort or group data. All-null columns may remain null or fail to provide a statistic. Dask/dtype support can constrain a chosen operation.

## Examples

Numeric input `amount` contains `10, null, 20`.

Parameter values (without an MCP patch envelope):

```json
{
  "fill_values": {
    "amount": "mean"
  }
}
```

The missing value becomes 15.

## Common errors

Validation rejects empty mappings, unknown columns and unsupported functions. For unsuitable numeric statistics, cast/clean the data first. Establish meaningful order before ffill/bfill.
