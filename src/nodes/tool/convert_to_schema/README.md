# ConvertToSchema

Node type: `ConvertToSchema`.

## Purpose and selection

Build a TableSchema from a DataFrame of column descriptions. It interprets input rows as schema records; it does not simply reflect the input DataFrame's own columns.

## Inputs and configuration

Connect the descriptor table to `df`. `column_names` names its column containing target field names. Optional mappings identify descriptor columns for dtypes, descriptions, nullable, defaults, order, primary_key, unique, precision, scale, length, format; `metadata_columns` retains additional attributes.

## Outputs

`schema` is a TableSchema object for consumers such as `SchemaPolicy.schema`. It is neither a DataFrame nor DataFrameMetadata.

## Behavior and limitations

Full execution materializes/validates the descriptor data via the data-catalog builder. Metadata-only mode emits an empty TableSchema without reading its rows; full execution is needed for data-defined fields. Conversion does not create a database table or cast business data.

## Examples

Connect descriptor rows `field=id,dtype=INT` and `field=name,dtype=STRING`. Output schema describes id and name. A separate business DataFrame can then be checked with SchemaPolicy.

Parameter values, without an MCP patch envelope:

```json
{
  "column_names": "field",
  "column_dtypes": "dtype"
}
```

## Common errors

Wrong schema names: mapping values must name descriptor columns, not desired output columns. Invalid/duplicate records: fix the descriptor data. Do not wire this TableSchema object directly into CreateTable.dataframe_metadata.
