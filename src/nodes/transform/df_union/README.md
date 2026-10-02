# DataFrameUnion

Node type: `DataFrameUnion`.

## Purpose and selection

Append the rows of two DataFrames. Use `DataFrameJoin` to match keys and combine columns instead.

## Inputs and configuration

Connect `df1` and `df2`. `column_mapping` maps a destination/left column name to the corresponding right column name: `{"id":"external_id"}` renames `df2.external_id` to `id`. Use `{}` when names already match.

## Outputs

`output` concatenates both inputs. Unmatched columns are retained with missing values for the other branch; duplicate rows remain.

## Behavior and limitations

Useful indexes are reset with collision-safe names. Invalid/absent right mapping entries are skipped; duplicate resulting column names are rejected. Shared datetime columns are normalized through UTC to timezone-naive nanosecond datetimes. Other incompatible dtypes may be promoted. No deduplication or business ordering is performed.

## Examples

`df1` has `id=1, amount=10`; `df2` has `external_id=2, amount=20`.

Parameter values, without an MCP patch envelope:

```json
{
  "column_mapping": {
    "id": "external_id"
  }
}
```

The output contains both rows under `id, amount`.

## Common errors

Unexpected extra columns: check mapping direction and names. Duplicate-name error: make the renamed right schema unique. Compare types and business meaning before concatenating.
