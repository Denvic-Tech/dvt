# SchemaPolicy

Node type: `SchemaPolicy`.

## Purpose and selection

Validate or adapt DataFrame columns according to an explicit TableSchema and per-column policies.

## Inputs and configuration

Connect DataFrame → `df` and TableSchema → `schema`. `policy.columns` must define exactly every schema column. Per-column defaults: on_missing=error, on_type_mismatch=error; on_missing can be fill (with fill_value) or ignore; mismatch can be cast, soft_cast or ignore. Global on_extra_columns defaults to error, with drop/ignore alternatives.

## Outputs

`output` is a DataFrame with the configured drops, additions and conversions.

## Behavior and limitations

Strict integer cast rejects fractional values; soft integer cast turns them into null. Soft conversions coerce invalid data to missing values. Filling adds a missing column, not null cells in an existing column. This implementation applies presence/type policies, not every schema constraint such as uniqueness or nullable. Work is partition-based and lazy; metadata success cannot prove all rows cast successfully.

## Examples

Connect a schema with id:INT and region:STRING, and data `id="7", debug="x"`. Output is integer id=7 and region=unknown; debug is dropped.

Parameter values, without an MCP patch envelope:

```json
{
  "policy": {
    "columns": {
      "id": {
        "on_type_mismatch": "cast"
      },
      "region": {
        "on_missing": "fill",
        "fill_value": "unknown"
      }
    },
    "on_extra_columns": "drop"
  }
}
```

## Common errors

Policy/schema mismatch: define every schema column and no extra policy keys. Duplicate input columns are rejected. Bad fill/cast values: fix data or deliberately select soft_cast and inspect resulting nulls.
