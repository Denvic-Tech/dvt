# ManageVariables

Node type: `ManageVariables`.

## Purpose and selection

Define or override several typed user variables. Use `CreateVariable` for a single independent definition.

## Inputs and configuration

Connect upstream maps to `input_variables`. Configure `defined_variables` as name → specification with `type` and exactly one of literal `value` or expression `value_input`. Optional `is_list_type=false`, `nullable=false`, `default` follow CreateVariable semantics.

## Outputs

`output_variables` holds the resulting variable map, including definitions that replace matching names.

## Behavior and limitations

Every expression is resolved against incoming variables, not against earlier definitions in this same node. Chain nodes for dependent definitions. Explicit defaults apply to resolved nulls before nullable; omitted default differs from default=null. Metadata mode can emit unresolved typed values; full mode must resolve them. Defaults must be literals.

## Examples

The output map includes `region=EU` and integer `batch_size=1000`. Connect it to downstream `input_variables`.

Parameter values, without an MCP patch envelope:

```json
{
  "defined_variables": {
    "region": {
      "type": "STRING",
      "value": "EU"
    },
    "batch_size": {
      "type": "INT",
      "value": 1000
    }
  }
}
```

## Common errors

Both/neither value fields: specify exactly one. Unknown expression name: inspect incoming edges or split dependent definitions. Invalid type or null: correct the value/default policy.
