# DataFrameReplaceValues

Node type: `DataFrameReplaceValues`.

## Purpose and selection

Replace whole values in one column using a dictionary. Use `DataFrameRegexReplace` for pattern-based substring edits.

## Inputs and configuration

Connect `df`; set `column_to_replace` and `dictionary` (old value → new value). JSON dictionary keys are strings.

## Outputs

`output` retains all columns and updates the chosen column.

## Behavior and limitations

Numeric and datetime keys are converted to the column's type. Unmatched values remain. Null-key aliases include `null`, `none`, `nan`, `nil` and the empty string. Some incompatible replacements force the column to string. For ordinary string keys, replacement values are stringified; do not assume that a JSON null replacement always becomes a missing value. Datetime matching accounts for the column timezone.

## Examples

Input `status` contains `new, done, pending`.

Parameter values (without an MCP patch envelope):

```json
{
  "column_to_replace": "status",
  "dictionary": {
    "new": "open",
    "done": "closed"
  }
}
```

The result is `open, closed, pending`.

## Common errors

Unexpected dtype or null behavior: inspect a small result and cast explicitly if needed. Missing column: verify metadata. Use a regex node for partial string matches.

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

New `params.pairs` entries contain `old`/`new`: JSON null differs from an empty string. Keys and values are coerced separately for each column; incompatible replacements produce string results. Replacements match original values without cascading. The editor uses `legacy_dictionary` to preserve existing dictionary semantics until replacement entries are edited.

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
        "pairs": [
          {
            "old": "new",
            "new": "open"
          },
          {
            "old": null,
            "new": "unknown"
          }
        ]
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
