# DataFrameSelectVariables

Node type: `DataFrameSelectVariables`.

## Purpose and selection

Aggregate DataFrame columns into named scalar variables. Use `DataFrameGroupByAgg` when the result should remain tabular.

## Inputs and configuration

Connect `df`; `selected_variables` maps each variable name to `source_column_name` and `agg_func`. Supported functions: `first`, `last`, `min`, `max`, `sum`, `mean`, `count`, `nunique`, `std`, `var`. The default mapping is empty.

## Outputs

`output_variables` contains inferred typed user variables. There is no DataFrame result port.

## Behavior and limitations

Full execution computes the requested scalar aggregations; equal column/function pairs are computed once per call. Missing scalar results become None. First uses Dask head and last uses tail, so boundary partitions and existing order matter. Metadata-only mode emits unresolved typed variables without computing aggregates. This node disables execution caching.

## Examples

`df.amount` contains `10, 20`.

Parameter values, without an MCP patch envelope:

```json
{
  "selected_variables": {
    "total": {
      "source_column_name": "amount",
      "agg_func": "sum"
    }
  }
}
```

The variable `total` is 30 and can feed downstream `input_variables`.

## Common errors

Missing column or invalid specification is rejected. Empty mapping creates no new variables. Do not use first/last to infer chronological extrema; use min/max or establish the intended order.
