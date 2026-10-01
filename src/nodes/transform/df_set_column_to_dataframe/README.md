# Attach Series to a DataFrame

Experimental/unstable node `SetColumnToDataFrame`.

Connect the target `df` and one or more Series to `column_data`.
Legacy `column_name` with one Series preserves the previous assignment behavior.

For multiple assignments use:
```json
{"column_bindings": [{"source": "price", "target": "new_price"}, {"source": "quantity", "target": "new_quantity"}], "overwrite_existing": false}
```
Sources refer to connected Series names, not node IDs or positions. Connected
Series names and result names must be unique. Missing sources and existing
target columns are errors unless `overwrite_existing` explicitly permits
existing target replacement. Unbound sources are ignored.

Series align by index; equal lengths do not guarantee matching rows.
`output` retains the target DataFrame and assigns the selected Series.

The UI presents a source-to-result table and supports multiple connections to
the same `column_data` port. Overwrite policy and schema preview are under
Additional. Wildcards do not apply to this binding table.

## Saved graph migration

Database migration `0063` automatically moves existing nodes to the new contract.
The result name moves to `column_bindings`; `source: null` selects the single connected
Series without guessing its runtime name. Index alignment and overwrite permission
(`overwrite_existing: true`) are preserved.
`input_bindings` keeps expression/link parameters dynamic: they are resolved through
the original ports on every execution. Editing the corresponding UI field replaces
only that binding with an explicit value; other bindings remain intact.

Old ports and migration bookkeeping are retained for rollback. Repeated upgrades
never overwrite configured contracts. Downgrade restores the original record when
the contract is unchanged; edited contracts remain stored, while the previous
application uses the retained old ports.
