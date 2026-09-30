# Commit Kafka Offsets

Node type: `CommitKafkaOffsets`.

## Purpose and selection

Explicitly acknowledge a finite Kafka batch after its destinations finish successfully.
Use with Read Kafka Messages, or independently with saved, resolved offsets JSON.
This node never reads message payload or computes a DataFrame.

## Inputs and configuration

- `connection`: required accessible Kafka Connection record with topic/group permissions.
- `offsets`: required JSON object. Use the ordinary single expression `kafka_offsets`
  after connecting Read.output_variables to input_variables.
- `signal_in`: connect the successful signal_out of **every required destination**.
  All connected signals must be active. Read.signal_out alone is not a write barrier.
  Leave unconnected only for an explicitly launched independent commit of saved JSON.
- `input_variables`: standard DVT variable inputs.

JSON requires schema_version=1, nonempty topic/group_id, and a partitions list.
Each entry requires a unique nonnegative integer partition and nonnegative integer next_offset.
Booleans, fractional positions, duplicate partitions and unknown versions fail.
Optional isolation_level defaults to read_committed; read_uncommitted is supported.
Optional cluster_id must match the actual cluster; an unavailable cluster identity also fails.
connection_id is diagnostic: another authorized connection to the same cluster is allowed.
Optional read_id, start_offset, last_message_offset, message_count, payload_bytes,
messages_read, bytes_read and stop_reason follow the Read JSON contract.

## Outputs

- `signal_out`: true only after all required acknowledgements finish.
- `signal_error`: standard pipeline error signal.
- `output_variables.kafka_commit_result`: JSON object with a partitions array.
  Each entry contains partition, requested, current (null if absent), resulting and status:
  committed, unchanged or already_ahead.
- `output_variables.kafka_partitions_committed`: number of partitions advanced by this call.

Result variables remain unresolved until success. There is no DataFrame output.

## Behavior and limitations

next_offset is the **next message position**, normally last_message_offset + 1.
It is not a message count. The whole batch read from Kafka is acknowledged, including
messages discarded by downstream filters or aggregations.

All entries, cluster context, topic/partitions and upper bounds are checked before sending
an explicit synchronous commit. Positions above the current upper bound fail.
The bound respects isolation_level; read_committed uses the stable transaction boundary.
Empty partitions is a successful no-op after context validation. Equal positions are unchanged;
older JSON is already_ahead and does not move the group backwards. No reset is performed.

There is no autocommit, group balancing, interprocess lock or atomic compare-and-set.
The user must ensure exclusive use of the consumer group across projects and external clients.
Monotonicity assumes no competing commits. Kafka acknowledgement and external writes are
separate operations: at-least-once processing may repeat writes after a failure between them.
Exactly-once and deduplication are not provided. Arbitrary JSON is not proof of successful processing.

Temporary transport errors have bounded retries (three attempts, 0.5/1 second delays;
30-second request timeout). Non-transient authorization/validation errors are not retried.
A partial failure, lost reply or cancellation after submission may leave some offsets saved.
No rollback is attempted; retry the original JSON once the cause is resolved.
STOP before submission prevents commit. Clients close without autocommit.
Metadata mode has no side effects or successful signal. Full runs always recheck Kafka;
saved execution results cannot substitute for Commit.

## Examples

Assume topic orders exists with partition 0 ending at least at position 201 and group
dvt-orders has committed position 100:

```json
{
  "offsets": {
    "schema_version": 1,
    "topic": "orders",
    "group_id": "dvt-orders",
    "partitions": [{"partition": 0, "next_offset": 201}]
  }
}
```

Connect GetExistKafkaConnection.connection to CommitKafkaOffsets.connection.
An independent run advances the group to 201 and reports:

```json
{"partitions":[{"partition":0,"requested":201,"current":100,"resulting":201,"status":"committed"}]}
```

For the normal pipeline, connect:
ReadKafkaMessages.output → transformations → WriteDataFrameToDBV3.df;
ReadKafkaMessages.output_variables → CommitKafkaOffsets.input_variables;
WriteDataFrameToDBV3.signal_out → CommitKafkaOffsets.signal_in.
Connect Kafka Connection.connection to both Kafka nodes.
Set offsets to the standard single expression `kafka_offsets`.
For two mandatory writers, connect both success signals.
Replaying the saved example at position 201 returns unchanged, with zero partitions advanced.

## Common errors

- Unresolved offsets: fully compute the original batch and finish each required destination.
  Accessing the variable does not trigger reading.
- Wrong cluster, topic, partition or position above the bound: check the selected connection,
  JSON and isolation level. JSON cannot authorize access.
- A destination failed or its signal is inactive: Commit will not run. Correct the destination
  and account for possible repeated writes.
- Commit outcome uncertain: inspect current positions or retry the same JSON. An error does
  not prove that no offsets changed.
