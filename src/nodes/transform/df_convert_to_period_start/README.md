# DataFrameConvertToPeriodStart

Node type: `DataFrameConvertToPeriodStart`.

## Purpose and selection

Calculate the start of a calendar period for grouping or reporting. It changes dates, without aggregating rows.

## Inputs and configuration

Connect `df`; set `column`. `period` defaults to `month`; supported values include `week`, `year`, `day`, `hour`, `minute`, `second`. Optional `new_column` preserves the source; otherwise it is overwritten.

## Outputs

`output` contains the period-start datetime column and other original fields.

## Behavior and limitations

Non-datetime values are parsed with invalid values becoming NaT. Weeks start on Monday. Month/year use calendar starts. The result has its timezone removed while retaining the computed local wall time. The node does not sort or group data.

## Examples

`created_at` is `2026-09-23 14:20:00`.

Parameter values, without an MCP patch envelope:

```json
{
  "column": "created_at",
  "period": "month",
  "new_column": "month"
}
```

`month` is `2026-09-01 00:00:00`; aggregate with `DataFrameGroupByAgg` afterward if needed.

## Common errors

Unexpected NaT: inspect parsing and DST-sensitive values. Wrong reporting boundary: establish the intended timezone before computing the period. Use a new column to retain the original timestamp.
