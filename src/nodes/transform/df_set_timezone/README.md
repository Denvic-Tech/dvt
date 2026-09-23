# DataFrameSetTimezone

Node type: `DataFrameSetTimezone`.

## Purpose and selection

Localize naive datetimes or convert timezone-aware datetimes in one column.

## Inputs and configuration

Connect `df`; set `column` and `timezone` (default `Europe/Moscow`) to a valid timezone name.

## Outputs

`output` replaces the chosen column with timezone-aware datetimes.

## Behavior and limitations

Non-datetime input is parsed, with invalid values becoming NaT. A naive timestamp keeps its clock time when localized. An aware timestamp preserves the instant when converted. Ambiguous or nonexistent local times become NaT during localization.

## Examples

Input is aware `2026-01-01 00:00:00+00:00`.

Parameter values, without an MCP patch envelope:

```json
{
  "column": "event_at",
  "timezone": "Europe/Moscow"
}
```

The result is `2026-01-01 03:00:00+03:00`. A naive midnight would instead become midnight in Moscow.

## Common errors

Wrong shift: distinguish localization from conversion. If naive values represent UTC, localize to UTC first, then convert. Verify timezone spelling and DST rules.
