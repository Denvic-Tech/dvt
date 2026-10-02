# ConvertVariablesToDataFrame

Node type: `ConvertVariablesToDataFrame`.

## Purpose and selection

Convert a variable map into one DataFrame row. Use it to persist or combine execution-level values.

## Inputs and configuration

Connect upstream `output_variables` → `input_variables`. The input must be a non-empty map of typed variables. There are no node-specific scalar configuration parameters.

## Outputs

`output` is a single-partition DataFrame with one column per variable and one row in full execution.

## Behavior and limitations

Scalar types map to pandas dtypes; lists and JSON remain object cells, not separate rows. Metadata-only execution creates the same columns with zero rows. Unresolved values are rejected in full execution.

## Examples

Create variables `region` (STRING, `EU`) and `count` (INT, 3), then connect their variable outputs.

Parameter values, without an MCP patch envelope:

```json
{}
```

Output has one row `region=EU, count=3`. Empty configuration is intentional; values arrive through edges.

## Common errors

Empty input: connect variable producers. Invalid payload: use typed variable outputs, not a plain dictionary of untyped values. Resolve dependencies before full execution.
