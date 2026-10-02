# JsonToDataFrame

Node type: `JsonToDataFrame`.

## Purpose and selection

Create a DataFrame from JSON records. Normalize nested documents with `JSONEditor` first.

## Inputs and configuration

Connect a parsed JSON value to `json`, preferably a list of row objects. A single dictionary becomes a one-row list. `orient` is exposed with default `columns`, but the current implementation does not use it.

## Outputs

`output` is a Dask DataFrame built from a materialized pandas DataFrame.

## Behavior and limitations

Uses `pd.DataFrame(json)` after wrapping a dictionary; it does not parse a JSON string, flatten nested objects, or interpret columns/index/tight orientation. Partition count is `max(1, len(json) // 100000)`. The entire input is in memory before partitioning.

## Examples

Connect JSON `[{"id":1,"amount":10},{"id":2,"amount":20}]` → `json`. Output has two rows and columns `id, amount`.

Parameter values, without an MCP patch envelope:

```json
{
  "orient": "columns"
}
```

## Common errors

Unexpected one-row nested data: supply records rather than a column-oriented dictionary. String input: parse it upstream. Mixed types: normalize records and cast downstream.
