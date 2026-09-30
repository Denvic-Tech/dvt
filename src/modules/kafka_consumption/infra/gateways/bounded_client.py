"""Bound the SDK's metadata/coordinator loops through its documented kafka_client hook."""

from contextvars import ContextVar
from time import monotonic

from kafka import KafkaClient
from kafka.errors import KafkaTimeoutError

# One operation per calling thread/context; no client or deadline is shared across Dask tasks.
operation_context = ContextVar("kafka_operation_context", default=None)


class BoundedKafkaClient(KafkaClient):
    def poll(self, timeout_ms=None, future=None):
        context = operation_context.get()
        if context is None:
            return super().poll(timeout_ms=timeout_ms, future=future)
        deadline, check_cancelled = context
        local_deadline = (
            min(deadline, monotonic() + timeout_ms / 1000) if timeout_ms is not None else deadline
        )
        responses = []
        while True:
            check_cancelled()
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise KafkaTimeoutError("Kafka operation deadline exceeded")
            wait_ms = min(100, remaining * 1000)
            if timeout_ms is not None:
                wait_ms = min(wait_ms, max(0, (local_deadline - monotonic()) * 1000))
            responses.extend(super().poll(timeout_ms=wait_ms, future=future))
            check_cancelled()
            if monotonic() >= deadline:
                raise KafkaTimeoutError("Kafka operation deadline exceeded")
            if (
                timeout_ms == 0
                or future is None
                or future.is_done
                or (timeout_ms is not None and monotonic() >= local_deadline)
            ):
                return responses
