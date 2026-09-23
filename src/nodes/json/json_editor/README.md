# JSONEditor

Node type: `JSONEditor`.

## Purpose and selection

Select records, flatten objects and selectively expand arrays before `JsonToDataFrame`. It also normalizes recognized tabular JSON matrices.

## Inputs and configuration

Connect `json`. Set explicit `record_path` for predictable record selection; otherwise `auto_detect_record_path=true` may choose a confident candidate. `meta_paths` copies fields into each row; `explode_paths` expands arrays; `keep_json_paths` preserves subtrees; `exclude_paths` removes subtrees. Paths beginning with `$` are absolute; other configuration paths are relative to a record. Defaults: `separator="."`, `max_rows=10000` (up to 100000).

## Outputs

`output` is a list of row dictionaries; kept JSON and non-exploded arrays remain nested values.

## Behavior and limitations

Exclusion takes precedence over keeping or exploding. Kept subtrees are not exploded. Multiple exploded arrays multiply combinations. Empty exploded arrays yield a null field. `max_rows` truncates the total output with a warning. A missing record path returns an empty list with a warning, not a hard error. Metadata mode also processes the JSON. Meta values are applied after flattened fragments and can overwrite same-named keys.

## Examples

Input `{"batch":"B1","items":[{"id":1},{"id":2}]}` → `json` produces rows `{id:1,batch:B1}` and `{id:2,batch:B1}`.

Parameter values, without an MCP patch envelope:

```json
{
  "record_path": "$.items",
  "meta_paths": [
    "$.batch"
  ],
  "auto_detect_record_path": false
}
```

## Common errors

Empty output: check the effective record path and logs. Duplicated rows: inspect explode combinations. Truncated output is not a complete extract; adjust the limit or split input deliberately.
