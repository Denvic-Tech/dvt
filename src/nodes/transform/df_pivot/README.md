# DataFramePivot

Node type: `DataFramePivot`.

## Purpose and selection

Aggregate long-form measurements into a wide table with one column per category.

## Inputs and configuration

Connect `df`; set `index` (row key), `column` (category axis), and non-empty `aggfunc` mapping measurement → `mean`, `sum`, `count`, `first` or `last`.

## Outputs

`output` has the selected row key as its index. Category values become column names. If several metrics create the same name, the first metric in `aggfunc` gets the short name and others receive metric prefixes, with further disambiguation as needed.

## Behavior and limitations

Duplicate row/category pairs are aggregated. The category axis is converted to known categories, which may require reading data. High cardinality can produce a very wide table. Metric inputs must be ordinary columns. First/last reflect data order, not a latest-by-date business rule.

## Examples

Rows are `(A, jan, 10)` and `(A, jan, 5)` in `region, month, amount`.

Parameter values, without an MCP patch envelope:

```json
{
  "index": "region",
  "column": "month",
  "aggfunc": {
    "amount": "sum"
  }
}
```

Region A has `jan=15` in the pivot result.

## Common errors

Empty/unsupported aggregation is rejected. If a downstream field is missing, inspect the actual flattened names and index. Reduce category cardinality before pivoting large data.
