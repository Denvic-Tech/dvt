# ExecuteSQL

Node type: `ExecuteSQL`.

## Purpose and selection

Execute database-side SQL when a specialized read/transform/write node cannot express the operation. Explain the reason in the MCP node comment.

## Inputs and configuration

Connect `GetExistDBConnection.connection` → `connection`; supply non-empty `sql_code` in the source dialect. Supported SQL templates can reference available input/project variables; follow the current SQL input schema.

## Outputs

`signal_out` activates on success. Row-returning SQL populates `output` as a one-partition DataFrame. Exactly one result row also emits one typed output variable per unique non-empty column name. Non-row SQL does not supply a tabular result.

## Behavior and limitations

Query results are materialized into pandas, so use ReadQueryFromDBV3 for large partitioned reads. Non-query SQL can mutate the database and executes inside a database transaction, subject to dialect behavior. Metadata mode skips non-result execution and describes result schemas; it does not certify runtime success or emit computed scalar variables. Consider side effects before rerunning.

## Examples

With a SQL connection supporting this syntax, the result has one row probe=1, output_variables contains probe, and signal_out is active. This is a minimal contract example.

Parameter values, without an MCP patch envelope:

```json
{
  "sql_code": "SELECT 1 AS probe"
}
```

## Common errors

SQL syntax/permission failures propagate. Missing variables may mean the result had zero/multiple rows or duplicate aliases. Do not connect output as a DataFrame for statements that return no rows.
