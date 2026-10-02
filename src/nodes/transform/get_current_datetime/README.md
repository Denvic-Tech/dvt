# GetCurrentDateTime

Node type: `GetCurrentDateTime`.

## Purpose and selection

Add an execution timestamp to every row, for example for load auditing.

## Inputs and configuration

Connect a DataFrame to `df` and set `column_name`. No separate timezone parameter is used.

## Outputs

`output` contains the input plus the named UTC-aware timestamp column; an existing column of that name is overwritten.

## Behavior and limitations

A single timestamp is captured when `process` runs and assigned to all rows, not sampled separately per row. Cached execution results can retain a previous timestamp; force actual execution when a new timestamp is required. No rows are created for an empty input.

## Examples

Connect a two-row DataFrame.

Parameter values, without an MCP patch envelope:

```json
{
  "column_name": "loaded_at"
}
```

Both rows receive the same UTC `loaded_at` value for that execution.

## Common errors

Unexpected old time: check execution/cache reuse. Unexpected overwritten field: choose an unused column name. Convert timezone downstream for presentation.
