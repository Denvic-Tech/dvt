# DataFrameGroupByAgg

Node type: `DataFrameGroupByAgg`.

## Purpose and selection

Group rows and calculate named aggregates, or aggregate the whole DataFrame.

## Inputs and configuration

Connect `df`. `group_by_columns=[]` selects global aggregation. Supply `new_cols`, `source_cols`, `agg_funcs` together as equal-length lists, or omit all three for unique group keys. `dropna=false` retains null-key groups. Functions: `sum`, `mean`, `min`, `max`, `count`, `first`, `last`, `nunique`, `std`, `var`.

## Outputs

`output` contains group keys and named results; global aggregation produces one row. With group keys but no aggregates, output contains unique key combinations.

## Behavior and limitations

Null-key filtering is controlled by `dropna`, not by filling source values. Indexes are reset safely for grouping and results; inspect resulting metadata. Output order is not guaranteed. First/last depend on existing order; global first/last skip nulls while scanning partitions. A completely empty grouping-and-aggregation specification is invalid.

## Examples

Rows `(EU,10)` and `(EU,20)` use `region, amount`.

Parameter values, without an MCP patch envelope:

```json
{
  "group_by_columns": [
    "region"
  ],
  "source_cols": [
    "amount"
  ],
  "agg_funcs": [
    "sum"
  ],
  "new_cols": [
    "total"
  ],
  "dropna": false
}
```

Output has region EU with `total=30`. Set `group_by_columns=[]` with the same aggregation lists for a single total over all regions.

## Common errors

Unequal or partially filled aggregation lists are rejected. Verify numeric types for arithmetic functions and unique result names. Use an explicit business rule before relying on first/last.
