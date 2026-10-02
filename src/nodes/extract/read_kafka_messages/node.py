from datetime import datetime
from typing import Literal, Optional

import dask.dataframe as dd
from pydantic import BaseModel

from src import utils
from src.logger import logger
from src.modules.kafka_consumption.domain.value_objects import ReadLimits
from src.modules.kafka_consumption.facade import (
    KafkaDaskReader,
    KafkaRuntimeSettings,
    PlanKafkaRead,
    ReadKafkaChunk,
    build_kafka_gateway,
)
from src.modules.kafka_consumption.infra.dataframe import (
    kafka_dataframe_metadata,
    messages_to_dataframe,
)
from src.modules.kafka_consumption.infra.mappers import offsets_to_json
from src.node_dsl import IO, DFOutputBaseNode, InputField, KafkaConnectionRecord, OutputField
from src.node_dsl.variables import UnresolvedValue, VariableOutput, build_variable_map_metadata
from src.node_dsl.variables.system_variables import build_system_variable_type_map
from src.runtime.async_runtime import async_worker


def _identity_partition(frame):
    # Keep the reader callback on a child expression when DFOutputBaseNode adds its own.
    return frame


class KafkaReadVariables(BaseModel):
    kafka_topic: str
    kafka_group_id: str
    kafka_read_id: str
    kafka_partitions: list[int]
    kafka_offsets: dict
    kafka_messages_read: int
    kafka_bytes_read: int
    kafka_stop_reason: str


class ReadKafkaMessages(DFOutputBaseNode):
    TITLE = "Read Kafka Messages"
    CATEGORY = "Extraction"
    ICON_KEY = "kafka-connection"
    DESCRIPTION = (
        "Read a finite lazy Kafka snapshot without committing. Use an exclusive group; "
        "at-least-once processing can repeat messages after failure. Final offsets resolve "
        "only after full computation; commit separately after successful destination signals."
    )
    CACHABLE = False
    REQUIRES_FRESH_EXECUTION = True
    EXPERIMENTAL = False
    DISABLED = False
    SYSTEM_VARIABLES_MODEL = KafkaReadVariables

    connection: KafkaConnectionRecord = InputField(
        description="Kafka connection",
        agent_description="Use an accessible Kafka Connection output; credentials remain in the connection record.",
    )
    topic: str = InputField(
        description="Topic",
        agent_description="Exact existing topic name; no regex or auto-creation.",
    )
    group_id: str = InputField(
        description="Consumer group",
        agent_description="Exclusive consumer group used for positions; this node never commits.",
    )
    partitions: list[int] | None = InputField(
        default=None,
        description="Partitions",
        agent_description="Null selects all snapshot partitions; otherwise provide unique existing nonnegative IDs.",
    )
    start_mode: Literal["committed", "earliest", "latest", "timestamp", "explicit"] = InputField(
        default="committed",
        description="Start mode",
        agent_description="Committed uses the group position. Latest is an empty snapshot, not streaming.",
    )
    missing_offset_policy: Literal["earliest", "latest", "error"] = InputField(
        default="earliest",
        description="Missing offset policy",
        agent_description="Applies only to absent committed positions; out-of-range positions always fail.",
    )
    start_timestamp: datetime | None = InputField(
        default=None,
        description="Start timestamp",
        agent_description="Timestamp mode requires a timezone-aware datetime; normalized to UTC.",
    )
    start_offsets: Optional[IO.JSON] = InputField(  # noqa: UP045 - IO is a DSL enum
        default=None,
        description="Start offsets",
        agent_description="Explicit mode requires a JSON object mapping every selected partition ID string to a position.",
    )
    max_messages: int | None = InputField(
        default=100_000,
        description="Maximum messages",
        agent_description="Positive total limit across all partitions; null disables the count limit.",
    )
    max_bytes: int | None = InputField(
        default=67_108_864,
        description="Maximum payload bytes",
        agent_description="Strict total raw key/value/header byte limit; null disables it. Messages are indivisible.",
    )
    key_format: Literal["text", "binary"] = InputField(
        default="binary",
        description="Key format",
        agent_description="Binary preserves bytes; text decodes strictly using key_encoding.",
    )
    value_format: Literal["text", "binary"] = InputField(
        default="text",
        description="Value format",
        agent_description="Text decodes strictly; binary preserves bytes. Tombstones remain null.",
    )
    key_encoding: str = InputField(
        default="utf-8",
        description="Key encoding",
        agent_description="Used only for text keys; invalid sequences fail without replacement.",
    )
    value_encoding: str = InputField(
        default="utf-8",
        description="Value encoding",
        agent_description="Used only for text values; no automatic JSON or Avro decoding.",
    )
    isolation_level: Literal["read_committed", "read_uncommitted"] = InputField(
        default="read_committed",
        description="Isolation level",
        agent_description="Read committed fixes the stable boundary and excludes aborted or pending transactions.",
    )
    rows_per_partition: int = InputField(
        default=10_000,
        description="Rows per Dask part",
        agent_description="Positive maximum rows per Dask part, independent of Kafka partition count.",
    )
    target_partition_bytes: int = InputField(
        default=8_388_608,
        description="Target bytes per Dask part",
        agent_description="Soft raw-byte target; one permitted message may exceed it.",
    )
    max_message_bytes: int = InputField(
        default=16_777_216,
        description="Maximum message bytes",
        agent_description="Hard protective limit for a single raw message; not a process memory cap.",
    )

    output: dd.DataFrame = OutputField()

    def _formats(self):
        precision = str(self.execution_settings.datetime_precision)
        return {
            "key_format": self.key_format,
            "value_format": self.value_format,
            "key_encoding": self.key_encoding,
            "value_encoding": self.value_encoding,
            "timestamp_unit": {"Nanoseconds": "ns", "Microseconds": "us", "Seconds": "s"}[
                precision
            ],
        }

    def _init_variables(self, plan=None):
        types = build_system_variable_type_map(self.SYSTEM_VARIABLES_MODEL)
        known = {"kafka_topic": self.topic, "kafka_group_id": self.group_id}
        if plan is not None:
            known.update(
                kafka_read_id=plan.read_id,
                kafka_partitions=[r.topic_partition.partition for r in plan.ranges],
            )
        self.output_variables = dict(self.output_variables or {})
        for name, var_type in types.items():
            self.output_variables[name] = VariableOutput(
                name=name,
                type=var_type,
                var_type="system",
                value=known.get(
                    name,
                    UnresolvedValue(
                        reason="Kafka snapshot has not been fully read",
                        declared_type=var_type,
                    ),
                ),
            )
        self.__dict__.pop("_resolved_metadata", None)

    def _invalidate(self):
        for name in (
            "kafka_offsets",
            "kafka_messages_read",
            "kafka_bytes_read",
            "kafka_stop_reason",
        ):
            variable = self.output_variables[name]
            variable.value = UnresolvedValue(
                reason="Kafka read incomplete", declared_type=variable.type
            )
        cached = self.__dict__.pop("_resolved_metadata", None)
        if cached is not None:
            cached["output_variables"] = build_variable_map_metadata(self.output_variables)

    def _publish(self, summary):
        self.cancellation.raise_if_requested()
        values = KafkaReadVariables(
            kafka_topic=summary.topic,
            kafka_group_id=summary.group_id,
            kafka_read_id=summary.read_id,
            kafka_partitions=[r.topic_partition.partition for r in self._reader.plan.ranges],
            kafka_offsets=offsets_to_json(summary),
            kafka_messages_read=summary.messages_read,
            kafka_bytes_read=summary.bytes_read,
            kafka_stop_reason=summary.stop_reason,
        ).model_dump()
        # Preserve VariableOutput references already handed to downstream nodes.
        offsets = values.pop("kafka_offsets")
        for name, value in values.items():
            self.output_variables[name].value = value
        self.output_variables["kafka_offsets"].value = offsets
        self.__dict__.pop("_resolved_metadata", None)
        async_worker.run(self._refresh_metadata())
        logger.info(
            "Kafka read {}: messages={}, bytes={}, partitions={}, stop={}",
            summary.read_id,
            summary.messages_read,
            summary.bytes_read,
            len(values["kafka_partitions"]),
            summary.stop_reason,
        )

    async def _refresh_metadata(self):
        metadata = await self.resolve_metadata()
        if self._metadata_cb:
            await utils.async_run_callable(
                self._metadata_cb,
                user_id=self.user_id,
                project_id=self.project_id,
                task_id=self.task_id,
                node=self,
                metadata=metadata,
            )

    def _gateway(self, settings):
        return build_kafka_gateway(
            properties=self.connection.properties,
            secrets=self.connection.secrets,
            check_cancelled=self.cancellation.raise_if_requested,
            settings=settings,
        )

    def process(self):
        formats = self._formats()
        messages_to_dataframe((), **formats)  # Validate encodings before network access.
        settings = KafkaRuntimeSettings()
        check = self.cancellation.raise_if_requested
        gateway = self._gateway(settings)
        plan = PlanKafkaRead(gateway, check).execute(
            topic=self.topic,
            group_id=self.group_id,
            partitions=self.partitions,
            start_mode=self.start_mode,
            missing_offset_policy=self.missing_offset_policy,
            start_timestamp=self.start_timestamp,
            start_offsets=self.start_offsets,
            isolation_level=self.isolation_level,
            connection_id=self.connection.id,
            limits=ReadLimits(
                self.max_messages,
                self.max_bytes,
                self.rows_per_partition,
                self.target_partition_bytes,
                self.max_message_bytes,
            ),
        )
        self._init_variables(plan)
        use_case = ReadKafkaChunk(gateway, check)
        self._reader = KafkaDaskReader(
            plan,
            read_chunk=use_case.execute,
            replay_chunk=use_case.replay,
            publish=self._publish,
            invalidate=self._invalidate,
            check_cancelled=check,
            formats=formats,
            max_plan_tasks=settings.max_plan_tasks,
        )
        frame = self._reader.dataframe()
        self.output = frame.map_partitions(_identity_partition, meta=frame._meta)

    def process_metadata(self):
        self._init_variables()
        formats = (self.key_format, self.value_format, self.key_encoding, self.value_encoding)
        if any(isinstance(value, UnresolvedValue) for value in formats):
            self.output = None
            return
        self.output = dd.from_pandas(messages_to_dataframe((), **self._formats()), npartitions=1)

    def infer_metadata(self):
        formats = (self.key_format, self.value_format, self.key_encoding, self.value_encoding)
        return {
            "output": None
            if any(isinstance(v, UnresolvedValue) for v in formats)
            else kafka_dataframe_metadata(**self._formats()),
            "output_variables": build_variable_map_metadata(self.output_variables),
        }
