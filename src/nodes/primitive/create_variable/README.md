# Create Variable

## Purpose and selection

`CreateVariable` defines one typed user variable for downstream nodes. Use `ManageVariables` to define several variables or manage the incoming variable set.

## Inputs and configuration

Set `name`, `type` and `value`. Types are `STRING`, `BOOLEAN`, `INT`, `FLOAT`, `DATETIME`, `TIMEDELTA`, `JSON`. `is_list_type=false` selects a scalar; true selects a list of the chosen supported element type. `nullable=false` rejects a resolved null unless `default` is supplied. `default` must be a literal and cannot come from an edge or expression. For expression values, connect upstream `output_variables` → `input_variables` and use the current expression schema.

## Outputs

`output_variables` contains the named typed variable. Connect this variable map to a consumer's `input_variables`; it is not a DataFrame port.

## Behavior and limitations

Values are converted to the declared type. When the resolved value is null, an explicitly supplied `default` takes precedence over `nullable`; otherwise nullable permits null, and the remaining case raises an error. Omitted default is the `UNSET` sentinel, distinct from explicit `default=null`, which is still a supplied default and can yield null even with `nullable=false`. A missing upstream variable or an unresolved expression is not a resolved null; default is not a missing-variable handler. Default does not rescue an invalid non-null value or an expression failure. Metadata-only execution can preserve unresolved expressions; full execution must resolve them. List expressions support only the single-expression form.

## Examples

Literal configuration values, without an MCP patch envelope:

```json
{"name":"batch_size","type":"INT","value":1000}
```

The output map contains integer `batch_size=1000`.

```json
{"name":"region","type":"STRING","value":null,"default":"unknown","nullable":false}
```

Here the output is `region="unknown"`. In an MCP patch, encode a literal null with the input-value schema; a bare null input update removes the saved input.

## Common errors

Null-value error: supply a meaningful literal default or enable nullable. Conversion error: match the actual value and declared type. Unresolved expression: verify incoming variable edges and names. Direct variable-link values are not supported when defining a variable; use a supported expression.
