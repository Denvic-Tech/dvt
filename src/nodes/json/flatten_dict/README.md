# ExpandJSON

Node type: `ExpandJSON`.

## Purpose and selection

Flatten nested objects and automatically expand arrays into record combinations. Prefer `JSONEditor` when expansion paths must be chosen explicitly.

## Inputs and configuration

Connect parsed data to `json`: an object or list of entries. Defaults: `separator="."`, `max_depth=15`, `max_array_size=100`, `max_total_rows=10000`.

## Outputs

`output` is a list of flattened dictionaries with the union of keys, sorted consistently and padded with null for absent fields.

## Behavior and limitations

Independent arrays create a Cartesian product, not element-wise pairing. Oversized arrays can be truncated; combinations exceeding the per-entry row budget are preserved as arrays instead of expanded. `max_total_rows` is applied separately to each top-level entry, not globally. `max_depth` currently limits structure analysis and warnings, not the actual flatten recursion. Empty arrays become null. Inspect logs when limits matter.

## Examples

Input `{"id":1,"tags":["a","b"]}` yields two records, with `tags=a` and `tags=b`, both with `id=1`.

Parameter values, without an MCP patch envelope:

```json
{
  "separator": ".",
  "max_array_size": 100,
  "max_total_rows": 10000
}
```

## Common errors

Unexpected row growth: inspect independent arrays. Remaining arrays or lost tail elements: inspect limit warnings. Use JSONEditor for controlled global row limits and explicit explode paths.
