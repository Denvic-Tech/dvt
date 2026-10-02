from types import SimpleNamespace

import pytest
from kafka.errors import KafkaTimeoutError
from kafka.future import Future

from src.modules.kafka_consumption.infra.gateways import bounded_client


@pytest.fixture
def polling(monkeypatch):
    state = SimpleNamespace(now=0.0, waits=[], cancelled=False)
    monkeypatch.setattr(bounded_client, "monotonic", lambda: state.now)

    def network_poll(self, timeout_ms=None, future=None):
        assert state.now < 1, "poll exceeded the test's bounded waiting window"
        state.waits.append(timeout_ms)
        state.now += max(timeout_ms / 1000, 0.000001)
        return ["response"]

    monkeypatch.setattr(bounded_client.KafkaClient, "poll", network_poll)
    client = object.__new__(bounded_client.BoundedKafkaClient)
    client._closed = True

    def check_cancelled():
        if state.cancelled:
            raise RuntimeError("cancelled")

    token = bounded_client.operation_context.set((0.5, check_cancelled))
    yield client, state
    bounded_client.operation_context.reset(token)


@pytest.mark.parametrize("future_state", ["absent", "pending", "done"])
def test_zero_timeout_never_waits_for_network_or_future(polling, future_state):
    client, state = polling
    future = None if future_state == "absent" else Future()
    if future_state == "done":
        future.success(None)
    responses = client.poll(timeout_ms=0, future=future)
    assert responses
    assert state.waits and all(wait == 0 for wait in state.waits)
    assert state.now < 0.00001
    if future_state == "pending":
        assert not future.is_done


def test_positive_timeout_bounds_future_wait(polling):
    client, state = polling
    future = Future()
    assert client.poll(timeout_ms=250, future=future)
    assert not future.is_done
    assert all(0 <= wait <= 100 for wait in state.waits)
    assert sum(state.waits) == pytest.approx(250)
    assert state.now == pytest.approx(0.25, abs=0.00001)


@pytest.mark.parametrize("timeout_ms", [None, 1000])
def test_operation_deadline_bounds_long_or_unspecified_timeout(polling, timeout_ms):
    client, state = polling
    with pytest.raises(KafkaTimeoutError):
        client.poll(timeout_ms=timeout_ms, future=Future())
    assert sum(state.waits) <= 500.001
    assert state.now <= 0.50001


@pytest.mark.parametrize("timeout_ms", [0, 100])
def test_expired_deadline_does_not_poll(polling, timeout_ms):
    client, state = polling
    state.now = 0.6
    with pytest.raises(KafkaTimeoutError):
        client.poll(timeout_ms=timeout_ms)
    assert not state.waits


@pytest.mark.parametrize("timeout_ms", [0, 100])
def test_cancellation_does_not_poll(polling, timeout_ms):
    client, state = polling
    state.cancelled = True
    with pytest.raises(RuntimeError, match="cancelled"):
        client.poll(timeout_ms=timeout_ms, future=Future())
    assert not state.waits
