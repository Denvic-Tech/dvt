# ExecutePython

Node type: `ExecutePython`.

## Purpose and selection

Run custom Python with optional DataFrame/JSON inputs when specialized nodes are insufficient. Explain that choice in the MCP node comment.

## Inputs and configuration

Set non-empty `code`. Optional edges feed `df_in` and `json_in`. The code sees `pd`, `dd`, `node`, `logger`, immutable input/project variables and mutable `output_variables`. Assign `df_out` and/or `json_out`.

## Outputs

`output` receives df_out (pandas is converted to one-partition Dask); `output_json` receives JSON-safe json_out; `signal_out` activates on success. Unassigned data outputs remain None.

## Behavior and limitations

Execution uses full Python builtins in the worker, not an isolated sandbox. Metadata-only mode does not run code; it publishes an empty DataFrame schema, empty JSON and an active signal. Thus arbitrary runtime output schemas cannot be proven by metadata alone. Explicit compute and large JSON outputs use worker memory; external side effects must account for reruns.

## Examples

This minimal contract example emits `{"ok":true}` at `output_json` and activates `signal_out`. It needs no data edges.

Parameter values, without an MCP patch envelope:

```json
{
  "code": "json_out = {'ok': True}"
}
```

## Common errors

Empty code, unsupported df_out or non-JSON-compatible json_out is rejected. A metadata success does not validate Python execution; run the intended target and inspect errors.
