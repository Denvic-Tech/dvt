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
