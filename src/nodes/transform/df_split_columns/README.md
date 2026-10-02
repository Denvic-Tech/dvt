# DataFrameSplitColumn

Node type: `DataFrameSplitColumn`.

## Purpose and selection

Split a text column into a fixed number of new columns.

## Inputs and configuration

Connect `df`; choose `column` and `delimiter`. `max_splits=1` produces two fields; generally it produces `max_splits + 1`. `drop_source=false` retains the original.

## Outputs

`output` adds `<column>_1`, `<column>_2`, etc., retaining or dropping the source as configured.

## Behavior and limitations

Each partition is split after converting the source to string. Missing split parts are padded with NaN. Null inputs are subject to string conversion. The delimiter follows pandas `str.split` defaults; multi-character patterns can be interpreted as regex. Existing destination-name collisions are not resolved.

## Examples

Input `code` is `A-42-X`.

Parameter values (without an MCP patch envelope):

```json
{
  "column": "code",
  "delimiter": "-",
  "max_splits": 1,
  "drop_source": false
}
```

`code_1=A`, `code_2=42-X`; `code` is retained.

## Common errors

Unexpected split positions: check delimiter/regex semantics. Missing pieces are allowed. Rename pre-existing `<column>_N` fields before splitting.

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

Split generates `<source>_1…N`; `drop_source` belongs to `params`.



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
            "value": "field_*"
          }
        ]
      },
      "params": {
        "delimiter": "-",
        "max_splits": 1,
        "drop_source": false
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
