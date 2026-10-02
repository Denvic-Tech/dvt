# DataFrameLagColumns

Node type: `DataFrameLagColumns`.

## Purpose and selection

Add shifted copies of columns for previous/next-row comparisons.

## Inputs and configuration

Connect `df`; set `columns_to_lag` and non-zero `lag_steps`. Positive shifts down, negative shifts up. `fill_value` defaults to null (leave missing values).

## Outputs

`output` adds `<column>_lagN` for positive steps or `<column>_lag-N` for negative steps.

## Behavior and limitations

Shift follows current row order, without sorting or grouping by an entity. A supplied fill value fills all nulls in the shifted series, including source nulls. The implementation attempts to restore the original dtype; nulls can make integer conversion fail later during lazy computation. Large shifts are subject to Dask partition constraints.

## Examples

An ordered, single-partition input has `amount=10, 20, 30`.

Parameter values (without an MCP patch envelope):

```json
{
  "columns_to_lag": [
    "amount"
  ],
  "lag_steps": 1,
  "fill_value": 0
}
```

`amount_lag1` is `0, 10, 20`; original values remain.

## Common errors

Zero steps are rejected. Verify every requested column, not just one: processing accesses each name. Establish order before lagging and use compatible fill values/dtypes.
