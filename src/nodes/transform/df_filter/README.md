# DataFrameFilter

Node type: `DataFrameFilter`.

## Purpose and selection

Split a DataFrame into matching and non-matching rows using structured conditions, without writing Python or SQL.

## Inputs and configuration

Connect `df`; set `conditions` to a `condition` or nested `and` / `or` groups with non-empty `conditions` lists. A condition has `left`, `operator`, and usually `right`. Operands are column, literal or canonical single expression; connect variables through `input_variables` when needed. `isnull` / `notnull` must omit `right`.

## Outputs

`output` contains matches; `inverted_output` contains the complementary rows. Both retain the input schema.

## Behavior and limitations

Comparisons support `==`, `!=`, `>`, `<`, `>=`, `<=`; membership uses `isin` / `notin`. Text operations `contains`, `startswith`, `endswith` are case-insensitive; contains is literal, not regex. Text/list operators require a literal or expression on the right. Literals are converted to the column type. Unresolved mask values become false. Metadata-only mode validates structure/column references but passes input through both outputs; it does not evaluate the filter.

## Examples

Input `amount` values are `50, 150, null`.

Parameter values, without an MCP patch envelope:

```json
{
  "conditions": {
    "kind": "condition",
    "left": {
      "type": "column",
      "column": "amount"
    },
    "operator": ">",
    "right": {
      "type": "literal",
      "value": 100
    }
  }
}
```

`output` contains 150; `inverted_output` contains 50 and null. Combine conditions with `{"kind":"and","conditions":[...]}` or `or`.

## Common errors

Unknown columns, empty groups and malformed operands fail validation. Use isnull/notnull for explicit null tests; relational comparisons with a null literal are rejected. Inspect `additional_schema.filter_rules_spec` for the current condition contract.
