# Add / modify columns by expression

Experimental node `DataFrameAddColumnByExpression`.

Legacy inputs `df`, `column_name`, and `expression` still calculate one field.
Expressions use pandas/Dask eval, not arbitrary Python statements.

For independent new fields, pass `calculated_columns`:
```json
{"calculated_columns": [{"name": "total", "expression": "price * quantity"}, {"name": "discounted", "expression": "price * 0.9"}]}
```
Every expression reads the original input. References to newly calculated fields,
duplicate output names, and collisions with existing columns are rejected.

For selected fields use `column_rules` as documented in
[Regex Replace](../df_regex_replace/README.md#multiple-column-rules), with
`params: {"expression": "__column__ * 2"}`.
The reserved `__column__` token denotes the current source column (not inside
quoted strings). The first matching enabled rule wins. Use `output.mode=new`
and a suffix or name mapping to retain sources. Do not combine
`calculated_columns` and `column_rules`.

UI offers two scenarios: transform columns or calculate new columns. Column
suggestions are available in the expression editor; extra settings and schema
preview are under Additional. Execution stays lazy and preserves the row index.

## Saved graph migration

Database migration `0063` automatically moves existing nodes to the new contract.
The original expression and result name move to `calculated_columns` without
substituting `__column__`. Existing overwrite permission is retained using
`overwrite_existing: true`.
`input_bindings` keeps expression/link parameters dynamic: they are resolved through
the original ports on every execution. Editing the corresponding UI field replaces
only that binding with an explicit value; other bindings remain intact.

Old ports and migration bookkeeping are retained for rollback. Repeated upgrades
never overwrite configured contracts. Downgrade restores the original record when
the contract is unchanged; edited contracts remain stored, while the previous
application uses the retained old ports.
