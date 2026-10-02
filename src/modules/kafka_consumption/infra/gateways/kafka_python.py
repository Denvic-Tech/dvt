import ssl
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from time import monotonic, sleep

from kafka import KafkaConsumer
from kafka.admin import KafkaAdminClient
from kafka.errors import KafkaError, OffsetOutOfRangeError
from kafka.structs import OffsetAndMetadata, TopicPartition as SDKTopicPartition

from src.logger import logger

from ...domain.entities import ReadBatch
from ...domain.exceptions import KafkaInputError, KafkaMessageTooLargeError
from ...domain.gateways.kafka import CheckCancelled
from ...domain.value_objects import IsolationLevel, OffsetRange, TopicPartition, nonnegative
from ..exceptions import KafkaCommitError, KafkaSnapshotLostError, KafkaUnavailableError
from ..mappers import message_from_sdk
from .bounded_client import BoundedKafkaClient, operation_context


@dataclass(frozen=True)
class KafkaRuntimeSettings:
    poll_timeout_ms: int = 1000
    request_timeout_ms: int = 30000
    no_progress_timeout_sec: float = 30
    attempts: int = 3
    max_fetch_bytes: int = 16_777_216
    max_plan_tasks: int = 10_000

    def __post_init__(self):
        for name in (
            "poll_timeout_ms",
            "request_timeout_ms",
            "attempts",
            "max_fetch_bytes",
            "max_plan_tasks",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise KafkaInputError(f"{name} must be a positive integer")
        if self.request_timeout_ms <= self.poll_timeout_ms or self.no_progress_timeout_sec <= 0:
            raise KafkaInputError("Invalid Kafka technical timeouts")


def _not_cancelled() -> None:
    pass


class KafkaPythonGateway:
    """Stateless factory of short-lived clients; no client is shared between threads."""

    def __init__(
        self,
        config: dict,
        *,
        settings: KafkaRuntimeSettings | None = None,
        check_cancelled: CheckCancelled = _not_cancelled,
    ):
        self._config = dict(config)
        self.settings = settings or KafkaRuntimeSettings()
        self._config["kafka_client"] = BoundedKafkaClient
        self._config["request_timeout_ms"] = self.settings.request_timeout_ms
        self._check_cancelled = check_cancelled

    def _retry(self, operation, name):
        for attempt in range(self.settings.attempts):
            self._check_cancelled()
            try:
                token = operation_context.set(
                    (
                        monotonic() + self.settings.request_timeout_ms / 1000,
                        self._check_cancelled,
                    )
                )
                try:
                    return operation()
                finally:
                    operation_context.reset(token)
            except ssl.SSLError:
                raise KafkaUnavailableError(f"Kafka {name} failed (TLS verification)") from None
            except OffsetOutOfRangeError:
                raise KafkaSnapshotLostError(f"Kafka range lost during {name}") from None
            except KafkaError as error:
                if not error.retriable or attempt + 1 == self.settings.attempts:
                    error_class = KafkaCommitError if name == "commit" else KafkaUnavailableError
                    detail = (
                        "; offsets may already be saved; retry the original JSON"
                        if name == "commit" else ""
                    )
                    raise error_class(f"Kafka {name} failed ({type(error).__name__}){detail}") from None
                deadline = monotonic() + 0.5 * (attempt + 1)
                while monotonic() < deadline:
                    self._check_cancelled()
                    sleep(min(0.1, max(0, deadline - monotonic())))

        raise KafkaUnavailableError(f"Kafka {name} exhausted attempts")

    @contextmanager
    def _consumer(self, *, group_id=None, isolation_level="read_committed"):
        if isolation_level not in {"read_committed", "read_uncommitted"}:
            raise KafkaInputError("Invalid isolation level")
        config = {
            **self._config,
            "group_id": group_id,
            "enable_auto_commit": False,
            "allow_auto_create_topics": False,
            "auto_offset_reset": "none",
            "isolation_level": isolation_level,
            "request_timeout_ms": self.settings.request_timeout_ms,
            "session_timeout_ms": min(10000, self.settings.request_timeout_ms - 1),
            "fetch_max_bytes": self.settings.max_fetch_bytes,
            "max_partition_fetch_bytes": self.settings.max_fetch_bytes,
        }
        consumer = self._retry(lambda: KafkaConsumer(**config), "connect")
        try:
            yield consumer
        finally:
            consumer.close(autocommit=False, timeout_ms=self.settings.request_timeout_ms)

    @staticmethod
    def _sdk(partition):
        return SDKTopicPartition(partition.topic, partition.partition)

    def partitions(self, topic: str) -> tuple[int, ...]:
        TopicPartition(topic, 0)
        with self._consumer() as consumer:
            result = self._retry(lambda: consumer.partitions_for_topic(topic), "metadata")
            if not result:
                raise KafkaInputError(f"Unknown or unavailable Kafka topic: {topic}")
            return tuple(sorted(result))

    def cluster_id(self) -> str | None:
        admin = self._retry(lambda: KafkaAdminClient(**self._config), "connect")
        try:
            return self._retry(admin.describe_cluster, "cluster metadata").get("cluster_id")
        finally:
            admin.close()

    def describe_metadata(self) -> Mapping[str, object]:
        """Load cluster/topic metadata without creating a consumer or touching offsets."""
        admin = self._retry(lambda: KafkaAdminClient(**self._config), "connect")
        try:
            cluster = self._retry(admin.describe_cluster, "cluster metadata")
            topics = self._retry(lambda: admin.describe_topics(), "topic metadata")
            return {"cluster": cluster, "topics": topics}
        finally:
            admin.close()

    def bounds(
        self, partitions: Sequence[TopicPartition], isolation_level: IsolationLevel
    ) -> Mapping[TopicPartition, tuple[int, int]]:
        if not partitions:
            return {}
        sdk = [self._sdk(p) for p in partitions]
        with self._consumer(isolation_level=isolation_level) as consumer:
            starts = self._retry(lambda: consumer.beginning_offsets(sdk), "beginning offsets")
            ends = self._retry(lambda: consumer.end_offsets(sdk), "end offsets")
            return {p: (starts[self._sdk(p)], ends[self._sdk(p)]) for p in partitions}

    def offsets_for_timestamp(
        self,
        partitions: Sequence[TopicPartition],
        timestamp_ms: int,
        isolation_level: IsolationLevel,
    ) -> Mapping[TopicPartition, int | None]:
        nonnegative(timestamp_ms, "timestamp_ms")
        if not partitions:
            return {}
        with self._consumer(isolation_level=isolation_level) as consumer:
            result = self._retry(
                lambda: consumer.offsets_for_times(
                    {self._sdk(p): timestamp_ms for p in partitions}
                ),
                "timestamp offsets",
            )
            return {
                p: None if result[self._sdk(p)] is None else result[self._sdk(p)].offset
                for p in partitions
            }

    def committed(
        self, group_id: str, partitions: Sequence[TopicPartition]
    ) -> Mapping[TopicPartition, int | None]:
        self._validate_group(group_id)
        if not partitions:
            return {}
        with self._consumer(group_id=group_id) as consumer:
            return {
                p: self._retry(
                    lambda p=p: consumer.committed(
                        self._sdk(p), timeout_ms=self.settings.request_timeout_ms
                    ),
                    "committed",
                )
                for p in partitions
            }

    def read(
        self,
        offset_range: OffsetRange,
        *,
        isolation_level: IsolationLevel,
        max_records: int,
        max_bytes: int | None,
        total_max_bytes: int | None,
        target_bytes: int,
        max_message_bytes: int,
    ) -> ReadBatch:
        for name, value in (
            ("max_records", max_records),
            ("target_bytes", target_bytes),
            ("max_message_bytes", max_message_bytes),
        ):
            nonnegative(value, name)
            if not value:
                raise KafkaInputError(f"{name} must be positive")
        for value in (max_bytes, total_max_bytes):
            if value is not None:
                nonnegative(value, "max_bytes")
        tp = self._sdk(offset_range.topic_partition)
        start, end = offset_range.start, offset_range.end
        if start == end:
            return ReadBatch((), start, True)
        with self._consumer(isolation_level=isolation_level) as consumer:
            consumer.assign([tp])

            def verify_range(position):
                beginning = self._retry(lambda: consumer.beginning_offsets([tp]), "range check")[tp]
                upper = self._retry(lambda: consumer.end_offsets([tp]), "range check")[tp]
                if beginning > position or upper < end:
                    raise KafkaSnapshotLostError(
                        f"Kafka snapshot lost: {tp.topic}/{tp.partition}, position={position}, end={end}"
                    )

            verify_range(start)
            consumer.seek(tp, start)
            messages = []
            payload_bytes = 0
            position = start
            progress_at = monotonic()
            poll_failed = False

            def poll_from_safe_position():
                nonlocal poll_failed
                if poll_failed:
                    verify_range(position)
                    # SDK poll can consume records before a failing network prefetch.
                    # Public seek invalidates its pending batch/stale fetch responses.
                    consumer.seek(tp, position)
                poll_failed = True
                result = consumer.poll(
                    timeout_ms=self.settings.poll_timeout_ms,
                    max_records=max_records - len(messages),
                )
                poll_failed = False
                return result

            while position < end:
                self._check_cancelled()
                polled = self._retry(poll_from_safe_position, "poll")
                for record in polled.get(tp, ()):
                    if record.offset >= end:
                        verify_range(position)
                        return ReadBatch(tuple(messages), end, True)
                    message = message_from_sdk(record)
                    size = message.payload_bytes
                    if size > max_message_bytes or (
                        total_max_bytes is not None and size > total_max_bytes
                    ):
                        raise KafkaMessageTooLargeError(
                            f"Kafka message too large: {tp.topic}/{tp.partition}/{record.offset}, "
                            f"bytes={size}, max_message_bytes={max_message_bytes}, "
                            f"max_bytes={total_max_bytes}"
                        )
                    if max_bytes is not None and payload_bytes + size > max_bytes:
                        verify_range(position)
                        return ReadBatch(tuple(messages), record.offset, False, True)
                    messages.append(message)
                    payload_bytes += size
                    position = record.offset + 1
                    progress_at = monotonic()
                    if len(messages) >= max_records or payload_bytes >= target_bytes:
                        verify_range(start)
                        return ReadBatch(tuple(messages), position, position >= end)
                scanned = min(
                    self._retry(
                        lambda: consumer.position(tp, timeout_ms=self.settings.request_timeout_ms),
                        "position",
                    ),
                    end,
                )
                if scanned > position:
                    position = scanned
                    progress_at = monotonic()
                if monotonic() - progress_at >= self.settings.no_progress_timeout_sec:
                    verify_range(position)
                    raise KafkaUnavailableError(
                        f"Kafka read made no progress: {tp.topic}/{tp.partition}, position={position}"
                    )
            verify_range(start)
            return ReadBatch(tuple(messages), position, True)

    @staticmethod
    def _validate_group(group_id):
        if not isinstance(group_id, str) or not group_id.strip():
            raise KafkaInputError("group_id must be nonempty")

    def commit(self, group_id: str, positions: Mapping[TopicPartition, int]) -> None:
        """Transport only: caller must apply monotonic_commit and validate all bounds first."""
        self._validate_group(group_id)
        for position in positions.values():
            nonnegative(position, "next_offset")
        if not positions:
            return
        offsets = {
            self._sdk(p): OffsetAndMetadata(position, "", -1) for p, position in positions.items()
        }
        submitted = False

        def submit(consumer):
            nonlocal submitted
            self._check_cancelled()
            submitted = True
            consumer.commit(offsets=offsets, timeout_ms=self.settings.request_timeout_ms)

        try:
            with self._consumer(group_id=group_id) as consumer:
                self._retry(lambda: submit(consumer), "commit")
                self._check_cancelled()
            self._check_cancelled()
        except BaseException as error:
            if submitted:
                note = (
                    "Kafka commit was submitted; some offsets may already be saved. "
                    "Cancellation/failure does not roll back offsets; retry the original JSON."
                )
                error.add_note(note)
                logger.warning(note)
            if isinstance(error, (KafkaError, ssl.SSLError)):
                raise KafkaCommitError(
                    f"Kafka commit/close failed ({type(error).__name__}); "
                    "offsets may already be saved; retry the original JSON"
                ) from None
            raise
