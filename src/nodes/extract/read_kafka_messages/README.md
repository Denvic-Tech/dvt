# Read Kafka Messages

Node type: `ReadKafkaMessages`.

## Purpose and selection

Read one finite Kafka topic snapshot as a lazy DataFrame. Use this node for scheduled batches
with explicitly acknowledged offsets. It never commits, subscribes to a consumer group, creates
topics, or waits for future messages. Use an existing Kafka Connection output.
Available as a stable node in UI and the ordinary MCP node catalog.

## Inputs and configuration

| Input | Default | Meaning |
| --- | --- | --- |
| `connection` | required | KafkaConnectionRecord delivered by a connection edge |
| `topic` | required | Exact existing topic name |
| `group_id` | required | Nonempty group used for saved positions |
| `partitions` | null | All current partitions; an explicit list must be nonempty, unique and available |
| `start_mode` | committed | committed, earliest, latest, timestamp or explicit |
| `missing_offset_policy` | earliest | earliest, latest or error, only when a committed position is absent |
| `start_timestamp` | null | Timezone-aware datetime required by timestamp mode |
| `start_offsets` | null | Explicit mode: JSON mapping every selected partition ID string to a position |
| `max_messages` | 100000 | Strict total message count; positive integer or null to disable |
| `max_bytes` | 67108864 | Strict total raw payload bytes; positive integer or null to disable |
| `key_format` / `value_format` | binary / text | binary or text |
| `key_encoding` / `value_encoding` | utf-8 | Strict decoding for text; ignored for binary |
| `isolation_level` | read_committed | Stable transaction boundary; read_uncommitted is an explicit alternative |
| `rows_per_partition` | 10000 | Maximum rows per Dask part, independent of Kafka partition count |
| `target_partition_bytes` | 8388608 | Soft raw-byte target per Dask part; may exceed by one allowed message |
| `max_message_bytes` | 16777216 | Hard raw-byte limit per message; not a process RAM limit |

Inherited `input_variables` and `signal_in` retain standard DVT behavior. Standard variable
references can configure inputs. Both total limits may be null; the fixed snapshot still bounds
the read. Plans exceeding the runtime limit of 10000 potential reading tasks fail before payload
reading; reduce the batch limits or increase part targets.

## Outputs

`output` is a lazy DataFrame with these Arrow columns:

- `topic`: string, `partition`: int32, `offset`: int64.
- `timestamp`: nullable UTC timestamp with execution-setting precision;
  `timestamp_type`: nullable CreateTime / LogAppendTime string.
- `key`, `value`: nullable string or binary according to configuration.
- `headers`: non-null list of structs `{key: string, value: binary}`.

Headers retain order, duplicate names and null values. Tombstones remain null, distinct from
empty strings/bytes. An empty output retains the same typed schema; payload is not decoded as
JSON, Avro or Protobuf.

`output_variables` includes `kafka_topic`, `kafka_group_id`, `kafka_read_id` (new UUID per
plan), and `kafka_partitions` (JSON). The following ordinary system variables start unresolved:
`kafka_offsets` (JSON), `kafka_messages_read` (integer), `kafka_bytes_read` (integer),
`kafka_stop_reason` (snapshot_exhausted / max_messages / max_bytes). Reading a variable never
computes the DataFrame. Full successful computation resolves existing variable references and
their metadata before a destination's success signal.

The offsets JSON contains schema_version=1, topic, group_id, read_id, available connection/cluster
IDs, isolation_level, statistics and a partitions list. Only partitions that returned messages
appear. Each next_offset is the last accepted message offset plus one, never a prefetched
consumer position. An empty batch publishes partitions=[] only after computation.

## Behavior and limitations

The plan fixes partitions and upper positions without reading payload. Later messages and
partitions belong to the next run. Committed positions outside the available range fail;
there is no automatic reset. Latest (including its missing-offset fallback) produces an empty
snapshot and never initializes the group. Repeated latest runs may remain empty indefinitely.
For “start now, then poll”, initialize group positions explicitly once and use committed.

Parts are read sequentially with a deterministic ascending cyclic partition traversal.
A part may span Kafka partitions; transformations/writes can run alongside later reads.
Order is preserved within each Kafka partition; there is no global timestamp ordering.
Byte accounting includes raw key/value and UTF-8 header names plus header values, not Kafka
overhead or pandas memory. A message that does not fit the remaining budget ends the batch
before that message. A message exceeding the entire byte budget or max_message_bytes fails.

Head, selected parts and pruned graphs do not publish whole-batch offsets unless the entire
original plan has actually been read and all original parts delivered. Recomputing uses the
same accepted ranges and verifies their fingerprints without double counting. Changed
previously read data, decoding errors and cancellation invalidate the read; start a new run.
Retention/compaction can remove history; numeric offset gaps alone do not prove data loss.

Only local synchronous and threaded schedulers are supported. The reader retains compact
receipts, not the whole payload. Each part is bounded by its row/soft-byte target plus one
allowed message. Fetch buffers and decoded data add memory overhead; a downstream compute
may still collect the entire DataFrame. Metadata mode never connects or reads payload.

Every run creates a fresh plan. Neither this node's store_enabled setting nor an old downstream
execution snapshot can replace its live execution path. Downstream snapshots remain useful for
viewing. Kafka autocommit is disabled on every path, including consumer closure.

Use an exclusive group: concurrent readers or external commits are the user's responsibility.
With explicit commit after successful destination signals, processing is at least once.
A failure between destination write and commit can repeat already written messages.
Exactly-once delivery and cross-system transactions are not provided. Filtering output rows
does not reduce the source batch to acknowledge.

## Examples

For an existing orders topic and connection:

```json
{"topic":"orders","group_id":"dvt-orders","start_mode":"committed","missing_offset_policy":"earliest","max_messages":1000,"value_format":"text"}
```

Connect `GetExistKafkaConnection.connection` → `ReadKafkaMessages.connection`, then
`ReadKafkaMessages.output` → transformations → a destination's DataFrame input.
For a SQL destination, select/convert supported columns first: arbitrary binary/nested support
is destination-specific. Pass `ReadKafkaMessages.output_variables` to the explicit commit
consumer's `input_variables`, and gate that consumer with the successful destination
`signal_out`. The Read node's own signal alone does not prove a completed destination write.
Use [Commit Kafka Offsets](../../tool/commit_kafka_offsets/README.md) for this acknowledgement;
connect every required destination's signal_out to its signal_in.

For a precise replay starting at position 100 of partition 0:

```json
{"topic":"orders","group_id":"dvt-orders","partitions":[0],"start_mode":"explicit","start_offsets":{"0":100},"max_messages":50}
```

Offsets 100..149 would produce next_offset=150 if all 50 messages exist and fit the byte limit.
With gaps, message_count and next_offset-start_offset can differ.

## Preview and connection security

The metadata viewer shows BINARY/LIST/STRUCT and the recursive Arrow schema, even for an empty
result. Cached-data preview represents each binary value as `<binary: N bytes>`, including values
inside headers; it does not decode or expose those bytes. Lists, structs, order, repeated header
names and null remain visible. This is a presentation summary, not a reversible export format;
the execution DataFrame keeps its original Arrow types and bytes. Store a downstream result
to inspect it: Read's own execution snapshot is disabled. Preview never acknowledges offsets.

Use the saved connection's PLAINTEXT/SSL/SASL_PLAINTEXT/SASL_SSL settings. PLAIN and
SCRAM-SHA-256/512 are supported, with optional custom CA PEM and certificate/hostname checking.
See [Kafka Connection](../../connection/get_exist_kafka_connection/README.md) for runtime
dependency and security limitations.

## Common errors

- Unknown topic/partition, missing group position with error policy, or unavailable offset:
  inspect the topic and choose a valid explicit start; missing and expired positions differ.
- Unresolved offsets: fully compute the original batch and depend on the destination's success
  signal; requesting the variable does not trigger reading.
- Decode error: use the actual text encoding or binary format; invalid bytes are not replaced.
- Oversized message: increase the applicable whole-message limit or fix producer payloads.
- Changed snapshot or STOP: do not acknowledge partial data; create a fresh run.
- Unsupported scheduler or excessive plan size: use local execution and smaller batch limits.
- Authentication/TLS errors: verify the saved connection and CA; secrets are not in output JSON.
