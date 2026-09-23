# AddTimeDeltaToDataFrame

Node type: `AddTimeDeltaToDataFrame`.

## Purpose and selection

Add a calendar offset to a datetime column, for example to calculate a due date.

## Inputs and configuration

Connect `df`; set `column_with_time` and `new_column_with_time`. `years`, `months`, `days`, `hours`, `minutes`, `seconds` default to 0. The schema also exposes `weeks`, `milliseconds`, `microseconds`, but the current implementation does not use them.

## Outputs

`output` contains the original DataFrame with the destination column added or overwritten.

## Behavior and limitations

Offsets use pandas DateOffset calendar rules. Implemented components are converted with `int`, so fractional parts are discarded. Validation accepts datetime/timedelta dtypes, but actual offset support still depends on the underlying operation; use datetime for calendar offsets. Input strings must be converted first.

## Examples

`created_at` is a datetime `2026-01-10 12:00:00`.

Parameter values, without an MCP patch envelope:

```json
{
  "column_with_time": "created_at",
  "new_column_with_time": "due_at",
  "days": 7
}
```

`due_at` becomes `2026-01-17 12:00:00`.

## Common errors

No change from weeks/subsecond settings: those fields are currently unused; express whole weeks through days. Type error: cast the source to datetime. Check the destination name to avoid overwriting needed data.
