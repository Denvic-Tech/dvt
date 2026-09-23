# ReadVariablesFromDB

Node type: `ReadVariablesFromDB`.

## Purpose and selection

Read small database-derived scalar or list variables without loading a full table into a DataFrame.

## Inputs and configuration

Connect a DB object to `connection`. Default `mode="manual"` requires non-empty `manual_variables`: name → table_name, column_name, aggregation, optional database_name/schema_name. Functions: min/max/count/count_distinct/sum/avg/first/last; first/last require order_by_column. In `mode="sql"`, set `sql_code`; optional `sql_variables` sets per-result-column policies. Policies include nullable=false, literal default, target_dtype and is_list_type=false.

## Outputs

`output_variables` contains typed variables; SQL result column names become variable names. There is no DataFrame output.

## Behavior and limitations

SQL must return at most one row with unique non-empty column names; multiple rows are rejected. No row becomes null values subject to default/nullable policies. Default is used before nullable and is distinct from an omitted default. Both full and metadata execution query the database. Execution caching is disabled. List mode describes a list in one value, not collecting multiple result rows. First/last order ties are not independently resolved.

## Examples

With a connected orders table whose largest id is 42, output `last_id=42`. For an empty table, the explicit default gives 0.

Parameter values, without an MCP patch envelope:

```json
{
  "mode": "manual",
  "manual_variables": {
    "last_id": {
      "table_name": "orders",
      "column_name": "id",
      "aggregation": "max",
      "default": 0,
      "target_dtype": "INT"
    }
  }
}
```

## Common errors

Too many SQL rows: aggregate or deliberately select one ordered row. Unknown sql_variables overrides: use actual result aliases. Null/conversion error: inspect defaults and target_dtype; input names remain sql_code even if an error message mentions sql_query.
