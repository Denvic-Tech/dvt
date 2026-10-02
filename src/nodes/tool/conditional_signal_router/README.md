# ConditionalSignalRouter

Node type: `ConditionalSignalRouter`.

## Purpose and selection

Choose which downstream execution branch receives an active signal. It routes execution, not DataFrame rows; use `DataFrameFilter` for rows.

## Inputs and configuration

Set Boolean `condition` or a supported expression. Supply referenced variables through `input_variables`. Use `signal_in` when execution must follow another node.

## Outputs

`then_signal` is active when the condition is true; `else_signal` when false. Connect them to downstream `signal_in`. This node deliberately has no ordinary `signal_out`.

## Behavior and limitations

Full execution activates exactly one branch. Metadata-only execution activates both so schemas can be collected for both branches. Execution caching is disabled. Do not interpret metadata reachability as a runtime decision.

## Examples

Connect `then_signal` → action A.signal_in and `else_signal` → action B.signal_in. Full execution activates A's incoming signal.

Parameter values, without an MCP patch envelope:

```json
{
  "condition": true
}
```

## Common errors

Unknown signal_out: use the named branch ports. Both branches appear in metadata: expected. Condition failure: check Boolean conversion and incoming variables.
