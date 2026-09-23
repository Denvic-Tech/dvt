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
