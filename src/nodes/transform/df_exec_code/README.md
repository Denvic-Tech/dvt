# DataFrameExecCode

Node type: `DataFrameExecCode`.

## Purpose and selection

Apply custom Python to a required DataFrame when specialized transformations do not express the task. Through MCP, explain the reason in the node comment.

## Inputs and configuration

Connect `df`; set `code` (default `df_out = df_in`). Code can use `df_in`, `pd`, `dd`, `node`, `logger`, immutable `input_variables` / `project_variables`, and the output variable map.

## Outputs

Assign a Dask DataFrame to `df_out`; it becomes `output`. Unlike ExecutePython, a pandas DataFrame is not automatically accepted.

## Behavior and limitations

Code runs with Python builtins in the worker, without a sandbox. Dask operations may remain lazy; explicit compute materializes data. This node does not override the base metadata execution path, so custom code can run while deriving metadata. Avoid external side effects in transforms.

## Examples

With a connected DataFrame, this contract example returns it unchanged. For a real use case, document why built-in nodes cannot express the required transform.

Parameter values, without an MCP patch envelope:

```json
{
  "code": "df_out = df_in"
}
```

## Common errors

Missing df_out or wrong output type raises an error. For a computed pandas result, explicitly wrap it with `dd.from_pandas`. Runtime Python errors are reported as code errors.
