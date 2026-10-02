# DataFrameCastColumnType

Node type: `DataFrameCastColumnType`.

## Purpose and selection

Convert selected column types before joins, arithmetic or writes.

## Inputs and configuration

Connect `df`; set `dtypes` to column → target dtype, for example `Int64`, `float64`, `string`, `datetime64[ns]`, `datetime64[ns, UTC]`.

## Outputs

`output` keeps the columns and values converted according to each target dtype.

## Behavior and limitations

Integer conversion truncates fractional parts toward zero, not rounding. Invalid numeric text raises an error. Use a nullable integer dtype for missing values. Datetime conversion parses with UTC and coerces invalid values to NaT; a naive datetime target removes timezone after UTC normalization, while a timezone target converts to that zone. Other types use ordinary `astype`. Lazy failures can surface only when computing.

## Examples

Numeric `qty` values are `2.9, -2.9, null`.

Parameter values (without an MCP patch envelope):

```json
{
  "dtypes": {
    "qty": "Int64"
  }
}
```

Values become `2, -2, null` in nullable integer form.

## Common errors

Conversion failure: inspect invalid values and target range. Unexpected date shift: check source offsets and UTC normalization. A Boolean cast is not a parser for arbitrary business strings.
