# DataFrame Join

## Purpose and selection

`DataFrameJoin` combines columns from two DataFrames by matching keys. Use it to enrich facts with a lookup table. Use `DataFrameUnion` to stack rows instead.

## Inputs and configuration

Connect DataFrame edges to `left` and `right`. Set `left_on` and `right_on` to lists of exact column names of equal length. `how` is `left` by default; other modes are `right`, `outer`, `inner`, `cross`. Although keys are optional in the schema, specify them explicitly for ordinary joins. `cross` ignores keys.

## Outputs

`output` is a DataFrame containing the joined columns. Conflicting non-key columns on the right receive `_right`; left names stay unchanged. Internal DVT columns are removed.

## Behavior and limitations

Duplicate keys produce all matching combinations: a left join can increase the row count. Validate uniqueness of lookup keys and compatible key types beforehand. Null keys follow the underlying DataFrame merge behavior; do not assume SQL NULL semantics. Row order is not guaranteed. Matching useful index names enable index joins; other useful indexes are reset before merging. Cross join forms the Cartesian product and can be very large. The fixed `_right` suffix does not resolve every possible naming collision; rename ambiguous columns first.

## Examples

Edges: sales → `left`, customers → `right`. Sales contain `customer_id=7, amount=100`; customers contain one row `id=7, name="Ada"`.

```json
{"left_on":["customer_id"],"right_on":["id"],"how":"left"}
```

These are parameter values, not an MCP graph patch. The output row contains both keys, `amount=100` and `name="Ada"`. An unmatched sale remains with null customer fields.

## Common errors

Unexpected extra rows: inspect duplicate key combinations on both sides. Missing key or dtype mismatch: inspect upstream metadata and normalize names/types. Overlapping columns after suffixing: rename before joining. Choose a business rule for duplicate lookup rows rather than arbitrarily discarding them.
