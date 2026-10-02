# DataFrameToJson

Node type: `DataFrameToJson`.

## Purpose and selection

Convert a small DataFrame into an in-memory JSON value, for API payloads or JSON processing.

## Inputs and configuration

Connect `df`. `orient` is `columns` (default), `index` or `tight`.

## Outputs

`output` is parsed JSON, not a serialized string or file path. Columns orientation maps column → index → value; index orientation maps index → column → value; tight contains index, columns, data and axis names.

## Behavior and limitations

The whole DataFrame is computed into pandas in memory. Columns/index orientations use JSON encoding with ISO dates and JSON nulls; tight is normalized with the shared JSON-safe converter. Duplicate axis labels can be incompatible with the selected orientation. This does not produce a records array.

## Examples

A one-row `df` with index 0 and `id=7` yields `{"id":{"0":7}}`.

Parameter values, without an MCP patch envelope:

```json
{
  "orient": "columns"
}
```

## Common errors

Memory pressure: reduce the input before converting. Wrong JSON shape: choose the intended orientation. Do not assume `JsonToDataFrame` reverses every orientation; its current implementation constructs records directly.
