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
Rules require datetime columns and integer offset components. `skip_incompatible: true` skips other types with a warning. Skipped columns remain claimed and do not fall through to later rules.


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
        "days": 7
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
