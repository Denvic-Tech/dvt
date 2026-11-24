# ReadQueryFromDBV3

Node type: `ReadQueryFromDBV3`.

## Purpose and selection

Read a query result as a partitioned DataFrame. Prefer ReadTableFromDBV3 plus low-code transforms for ordinary extraction; explain necessary source-side SQL in the node comment.

## Inputs and configuration

Connect `GetExistDBConnection.connection` → `connection`. Set `sql_code`, not `query`, to one SELECT/WITH/set-operation statement. Set `partition_col` to an exact exposed scalar result column/alias without SQL quotes. Optional `partition_grouping`, `npartitions`, `max_rows_per_partition`, `limit` tune reading. Optional `max_concurrent_queries` caps how many partition queries this reader runs at once; omit it to use the instance default for the database type.

Before configuring partitioning, assess the query result's size, selected row width, key nulls, cardinality and skew; base-table statistics alone may not describe joins or aggregation. `suggest_read_partitioning` (MCP; Gateway `POST /db-connections/{connection_id}/partitioning-advice`) with this `sql_code` profiles result columns the way the reader embeds the query and returns statistics, the planner's target partition count and row ceiling, ranked node-ready settings and excluded columns with reasons; query mode supports PostgreSQL, MySQL, Oracle and ClickHouse. Record the source-side SQL justification and partitioning decision in the node comment. Input `agent_description` metadata provides additional configuration guidance.

## Outputs

`output` is a Dask DataFrame containing query result fields.

## Behavior and limitations

The query must be suitable for the read planner's partitioned execution. Prefer stable non-null partition keys. Partition settings do not aggregate business data or guarantee row order. Metadata inference describes query columns against the source; unresolved/empty SQL can give empty metadata. It does not prove full execution succeeds.

If `npartitions` is omitted, the planner estimates the target count from the query result and instance settings. Default segmentation uses ranges for orderable non-null keys and hash buckets otherwise. Range boundaries are read with one sorting query on ClickHouse, PostgreSQL, SQL Server, MySQL 8 and Oracle; SQLite, a server without window functions or a failed query fall back to one query per boundary. An explicit range mode rejects null keys. `max_rows_per_partition` is a per-segment row ceiling. With custom `partition_grouping` modes (other than `range` and `hash`), a group whose exact row count exceeds it is split into `ceil(rows / floor(0.8 × max_rows_per_partition))` sub-segments by a hash of the full key value. Planning fails before any data is read, naming the group, its row count and the reason, when an oversized group cannot be split: the null group, a group of a single key value (for example `as_is`, one `explicit_values` value or a boolean value), or splitting would need more segments than the instance partition limit. Hashing cannot spread identical key values, so one value repeated more often than the ceiling inside a prefix, period or range group still fails while reading, and the error names the segment. Automatic and explicit range/hash segments are not split. On ClickHouse the planner counts the most repeated result key value before building them; when that value or the null group alone exceeds `max_rows_per_partition`, planning fails before any data is read, naming the key, the value, its row count and the ceiling. Other sources skip this check, so such a key still fails while reading. Planning and reading can evaluate the query more than once, including count/sample queries; use stable results and account for source cost. A result key may also be the output index while remaining a data column. With range segmentation, a fractional Decimal/numeric key becomes an index of exact `Decimal` values, while its selected column is float64.

Each segment runs the query separately. At most `max_concurrent_queries` segment queries of one reader run at the same time. When it is omitted, the instance applies a default per database type, which an operator can override or switch off. Other segments wait for a free slot, however many threads the consuming node uses. More concurrent queries are not always faster: drivers such as psycopg and pyodbc can slow down under thread contention, while server-bound sources such as ClickHouse can gain. The limit does not change segments, rows or ordering.

For ClickHouse, segment queries of one reader reuse a small pool of driver connections instead of opening one per segment. When the source reports for every result column an integer of up to 64 bits, Float32/Float64, Bool, String, Date/Date32, DateTime/DateTime64 or Decimal, also inside Nullable or LowCardinality, segments are fetched in the Arrow format, which converts strings and decimals faster; output values and types are the same as on the regular path. Any other or unknown column type, for example UUID, FixedString, Enum, IPv4, Int128, Array, Map, Tuple or JSON, sends every segment through the regular path. A segment the Arrow format cannot convert identically, such as invalid UTF-8 text or a date outside the supported range, is re-read through the regular path, so its result or error stays the same. DateTime64 with a precision other than 0, 3, 6 or 9 is readable only through Arrow: if another column sends the read through the regular path, such a column fails. The reader uses the ClickHouse HTTP interface: a connection with the native driver on the default native port (9000, or 9440 with TLS) is redirected to the default HTTP port (8123 or 8443) with a warning in the log, and a native connection on any other port fails with an error asking for the http driver and the server HTTP port.
A result key may also be the output index while remaining a data column.

For PostgreSQL, when the instance has the ADBC PostgreSQL driver, segments are fetched in the Arrow format (binary `COPY`) through a small pool of connections opened with the same connection settings, which is several times faster for large reads. This applies when every result column of the query is smallint, integer, bigint, numeric, real, double precision, boolean, text, varchar, char, name, date, timestamp, timestamptz, uuid, an enum, json or jsonb. Reads of fewer than 100,000 rows stay on the regular path because opening the Arrow connections costs more than it saves. Output values and types are the same as on the regular path. Any other column type, for example time, interval, bytea, money, inet or an array, sends every segment through the regular path, as do a range index over a fractional numeric key, a range key that is neither an integer nor a selected column, connection settings that cannot be reproduced exactly, and servers older than PostgreSQL 12 or without UTF-8 client encoding. A segment the Arrow format cannot convert identically, such as a date or timestamp outside the years 1 to 9999 or infinity, is re-read through the regular path, so its result or error stays the same. If the server rejects the Arrow connection, the reader uses the regular path for the rest of the read and logs a warning. Idle Arrow connections close about a second after the last segment query. An operator can switch the Arrow path off.

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

Partition column missing: select and alias it explicitly. Multiple statements/non-query SQL are rejected by the node policy. Check SQL dialect, source permissions and supported grouping for the result key. Group or segment above `max_rows_per_partition`: a planning error names a group that cannot be split; a reading error names a segment that still holds too many rows, usually one repeated key value. Raise `max_rows_per_partition`, use a finer grouping or choose another key. A planning error naming a partition key value means that value or the null group alone exceeds the ceiling of range/hash segments: pick a key recommended by `suggest_read_partitioning` or raise `max_rows_per_partition` above the reported count.
