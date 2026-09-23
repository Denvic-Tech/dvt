# DataFrameNumericNormalizer

Node type: `DataFrameNumericNormalizer`.

## Purpose and selection

Clip numeric values to bounds. Despite the name, this node does not scale values to a normalized distribution.

## Inputs and configuration

Connect `df`. `columns_to_normalize` selects fields; omitted/empty selects all candidates. Set `lower_border` and `upper_border` explicitly: both default to 0. `replace_empty_values=true` fills nulls with the lower bound.

## Outputs

`output` retains all columns; selected integer/float columns are clipped.

## Behavior and limitations

Values below/above the bounds become the nearest bound. Non-numeric fields and absent selected names are skipped; no suitable numeric columns is an error. Timedelta and complex types are not normalized. Equal bounds are allowed and collapse non-null numbers to a constant.

## Examples

`score` is `-5, 50, 120, null`.

Parameter values (without an MCP patch envelope):

```json
{
  "columns_to_normalize": [
    "score"
  ],
  "lower_border": 0,
  "upper_border": 100,
  "replace_empty_values": true
}
```

The result is `0, 50, 100, 0`.

## Common errors

All zeros: check the default upper bound. Lower greater than upper is rejected. Numeric-looking strings must be cast before clipping.
