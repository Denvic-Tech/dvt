# DataFrameRegexReplace

Node type: `DataFrameRegexReplace`.

## Purpose and selection

Replace matching text within one column using a regular expression.

## Inputs and configuration

Connect `df`; set `column_to_replace`, `pattern` and `replacement`. Replacement defaults to the empty string, which removes matches.

## Outputs

`output` keeps the DataFrame shape and replaces values in the selected column.

## Behavior and limitations

The column is converted with `astype(str)` before regex replacement. Numeric values and missing-value representations therefore become text; this is not a null-preserving numeric transform. All matching occurrences are processed by the underlying string operation.

## Examples

Input `code` is `AB-123`.

Parameter values (without an MCP patch envelope):

```json
{
  "column_to_replace": "code",
  "pattern": "[^0-9]",
  "replacement": ""
}
```

The output value is the string `123`.

## Common errors

Invalid regex: correct the expression and JSON escaping. Wrong result type: add an explicit cast afterward. Pass a string replacement, not null.

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
            "value": "field_*"
          }
        ]
      },
      "params": {
        "pattern": "\\s+",
        "replacement": " "
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
