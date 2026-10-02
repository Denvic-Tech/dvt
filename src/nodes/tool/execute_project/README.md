# ExecuteProject

Node type: `ExecuteProject`.

## Purpose and selection

Start another DVT project. Use it to coordinate reusable child pipelines; its output is a completion/dispatch signal, not the child's data.

## Inputs and configuration

Set `target_project_id` to the accessible project's immutable ID; `target_project_name` is a display label. `wait_for_completion=false` by default. With waiting enabled, optional `timeout_sec` limits each child wait; `cancel_on_timeout=false` leaves the child running after timeout. Optional `variables_df` is a DataFrame edge and requires `wait_for_completion=true`. Base values come from `input_variables`. `unresolved_variables_policy` defaults to `error`; `system_variables_policy` defaults to `include`.

## Outputs

`signal_out` becomes true after dispatch, or after successful waits when enabled. No child DataFrame or child output variables are returned.

## Behavior and limitations

Without `variables_df`, one child is submitted. With it, the entire frame is computed in memory and each row starts one child sequentially; row columns override base variables with the same names. Column names must be unique non-empty strings; nulls and pandas/numpy scalars are normalized. An empty frame starts no children. Metadata mode starts no tasks. Nested synchronous runs are subject to runtime capacity and access checks; a later failure does not undo completed children.

## Examples

Assume the selected child accepts variable `region`. Connect a frame with rows {region: "north"}, {region: "south"} to `variables_df` and set:

```json
{
  "target_project_id": "child-project-id",
  "wait_for_completion": true,
  "timeout_sec": 300,
  "cancel_on_timeout": false
}
```

The north run finishes before south starts; the signal follows both successful runs. Without the DataFrame edge, this configuration starts one child with base variables.

## Common errors

Using variables_df without waiting fails validation. Duplicate/blank column names are invalid. For an inaccessible project or insufficient nested-wait capacity, correct access/capacity before retrying. A timeout with cancel_on_timeout=false is not proof that the child stopped; check its task before rerunning.
