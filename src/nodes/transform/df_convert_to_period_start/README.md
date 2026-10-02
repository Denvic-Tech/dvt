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

## Multiple-column rules

Optional `column_rules` takes precedence over the single-column settings.
Omitting it preserves existing graph parameters and behavior.

Each rule has a unique `id`, a `selector`, and operation-specific `params`.
`selector.tokens` accepts `name` (exact name), `mask` (`*` and `?`
wildcards), or `all`. Tokens form a deduplicated union, narrowed by `types`
(text, number, datetime, boolean, timedelta, other), `exclude`, and optional
`name_regex`. Masks are case-sensitive; other mask characters are literal.
Masks and all-column selection are resolved again on each execution.

Only the first matching enabled rule applies to a column. Set `enabled: false`
to disable a rule. Every operation reads the original input: generated columns
are not selected by subsequent rules. A missing exact name is an error; an empty
dynamic selection is a no-op with a warning. Output name collisions are errors.

The default replaces the source. To create columns use `output: {"mode": "new", "suffix": "_result"}`. `output.names` overrides individual result names (source → target). New names must not collide with input columns.



DVT UI combines exact names, masks, and All columns in one field. Types,
exclusions, result names, rule priority, and disabling are under Additional.
The schema preview shows the effective rule and result names; it does not
execute a data sample.

Example (matching source columns must exist):

```json
{
  "column_rules": [
    {
      "id": "group-1",
      "selector": {
        "tokens": [
          {
            "kind": "mask",
            "value": "date_*"
          }
        ]
      },
      "params": {
        "period": "month"
      }
    }
  ]
}
```

## Saved graph migration

Database migration `0063` automatically moves existing nodes to the new contract.
Migrated rules use `compatibility: "v1"` to preserve prior dtype handling, empty
parameter values, and previously permitted overwrites. In particular, fractional
offsets remain truncated instead of failing the new parameter schema.
`input_bindings` keeps expression/link parameters dynamic: they are resolved through
the original ports on every execution. Editing the corresponding UI field replaces
only that binding with an explicit value; other bindings remain intact.

Old ports and migration bookkeeping are retained for rollback. Repeated upgrades
never overwrite configured contracts. Downgrade restores the original record when
the contract is unchanged; edited contracts remain stored, while the previous
application uses the retained old ports.
