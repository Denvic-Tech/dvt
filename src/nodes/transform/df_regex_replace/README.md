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
