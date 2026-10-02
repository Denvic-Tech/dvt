# ReadQueryFromDBV3

Node type: `ReadQueryFromDBV3`.

## Purpose and selection

Read a query result as a partitioned DataFrame. Prefer ReadTableFromDBV3 plus low-code transforms for ordinary extraction; explain necessary source-side SQL in the node comment.

## Inputs and configuration

Connect `GetExistDBConnection.connection` → `connection`. Set `sql_code`, not `query`, to one SELECT/WITH/set-operation statement. Set `partition_col` to an exact exposed scalar result column/alias without SQL quotes. Optional `partition_grouping`, `npartitions`, `max_rows_per_partition`, `limit` tune reading.

Before configuring partitioning, assess the query result's size, selected row width, key nulls, cardinality and skew; base-table statistics alone may not describe joins or aggregation. Record the source-side SQL justification and partitioning decision in the node comment. Input `agent_description` metadata provides additional configuration guidance.

## Outputs

`output` is a Dask DataFrame containing query result fields.

## Behavior and limitations

The query must be suitable for the read planner's partitioned execution. Prefer stable non-null partition keys. Partition settings do not aggregate business data or guarantee row order. Metadata inference describes query columns against the source; unresolved/empty SQL can give empty metadata. It does not prove full execution succeeds.

If `npartitions` is omitted, the planner estimates the target count from the query result and instance settings. Default segmentation uses ranges for orderable non-null keys and hash buckets otherwise. An explicit range mode rejects null keys. `max_rows_per_partition` fails an oversized segment; it does not automatically split it. Planning and reading can evaluate the query more than once, including count/sample queries; use stable results and account for source cost. A result key may also be the output index while remaining a data column.

## Examples

Assume the connected database has these columns. This minimal contract example exposes `id, amount`; for this ordinary read, use ReadTableFromDBV3 in a real graph unless additional source-side behavior justifies SQL.

Parameter values, without an MCP patch envelope:

```json
{
  "sql_code": "SELECT id, amount FROM orders",
  "partition_col": "id"
}
```

## Common errors

Partition column missing: select and alias it explicitly. Multiple statements/non-query SQL are rejected by the node policy. Check SQL dialect, source permissions and supported grouping for the result key.
