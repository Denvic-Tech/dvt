"""Tap implementation: the private Dask touch points it relies on and its own rules."""

import logging
import pickle
import threading
import uuid

import dask
import dask.dataframe as dd
import numpy as np
import pandas as pd
import pytest
from dask.base import is_dask_collection
from dask.callbacks import Callback, local_callbacks
from dask.dataframe.dask_expr._expr import MapPartitions

import core.dask_lifecycle.tap as tap_module
from core.dask_lifecycle import (
    OutputLifecycleHandlers,
    attach_lifecycle,
    delayed_partitions,
)
from core.dask_lifecycle.tap import LifecycleTapExpr, _Attachment, _attachment_id


def _frame(npartitions: int = 4) -> dd.DataFrame:
    rng = np.random.default_rng(int(uuid.uuid4().int % 2**32))
    return dd.from_pandas(pd.DataFrame({"a": rng.random(40)}), npartitions=npartitions)


def _counting_handlers(events: list) -> OutputLifecycleHandlers:
    return OutputLifecycleHandlers(
        on_start=lambda: events.append("start"),
        on_end=lambda: events.append("end"),
        on_error=lambda: events.append("error"),
        on_partition=lambda _partition, part_no: events.append(part_no),
    )


def _attach(frame, handlers):
    return attach_lifecycle(frame, handlers)


def test_tap_tasks_are_keyed_by_attachment_and_partition_number():
    attached = _attach(_frame(), _counting_handlers([]))

    assert type(attached.expr) is LifecycleTapExpr
    assert isinstance(attached.expr, MapPartitions)
    attachment = attached.expr.operand("kwargs")["lifecycle"]
    tap_keys = [
        key
        for key in dict(attached.optimize(fuse=False).__dask_graph__())
        if _attachment_id(key) is not None
    ]
    assert {_attachment_id(key) for key in tap_keys} == {attachment.id}
    assert len({key[0] for key in tap_keys}) == 1
    assert sorted(key[1] for key in tap_keys) == [0, 1, 2, 3]


def test_tap_expression_is_a_collection_without_materialising_its_graph(monkeypatch):
    attached = _attach(_frame().sort_values("a"), _counting_handlers([]))
    graph_calls: list[int] = []
    monkeypatch.setattr(
        LifecycleTapExpr, "__dask_graph__", lambda _self: graph_calls.append(1) or {}
    )

    assert is_dask_collection(attached.expr)
    assert graph_calls == []


def test_scheduler_state_exposes_task_dependencies():
    seen: dict = {}

    class _StateProbe(Callback):
        def _start_state(self, dsk, state):
            seen.update(
                {key: set(deps) for key, deps in state["dependencies"].items()}
            )

    attached = _attach(_frame(), _counting_handlers([]))
    with _StateProbe():
        attached.assign(b=1).compute(scheduler="sync")

    tap_keys = [key for key in seen if _attachment_id(key) is not None]
    assert len(tap_keys) == 4
    assert all(seen[key] for key in tap_keys)
    assert any(tap_key in deps for deps in seen.values() for tap_key in tap_keys)


def test_default_to_delayed_fuses_the_taps_away():
    """Why ``delayed_partitions`` exists: default ``to_delayed()`` fuses a chain of taps into
    tasks with new names, so the run no longer shows them."""

    def chain(events_a: list, events_b: list):
        a = _attach(_frame(), _counting_handlers(events_a))
        return _attach(a.assign(b=a.a * 2), _counting_handlers(events_b))

    events_a: list = []
    events_b: list = []
    dask.compute(*chain(events_a, events_b).to_delayed())
    assert events_a == []
    assert events_b == []

    dask.compute(*delayed_partitions(chain(events_a, events_b)))
    for events in (events_a, events_b):
        assert events[0] == "start"
        assert events[-1] == "end"
        assert sorted(events[1:-1]) == [0, 1, 2, 3]


def test_error_handler_failure_is_logged_and_the_computation_error_propagates(caplog):
    def broken_on_error():
        raise ValueError("handler is broken")

    def fail(frame, partition_info=None):
        if partition_info["number"] == 1:
            raise RuntimeError("boom")
        return frame

    attached = _attach(
        _frame(),
        OutputLifecycleHandlers(on_start=lambda: None, on_error=broken_on_error),
    )

    with (
        caplog.at_level(logging.ERROR, logger="core.dask_lifecycle.tap"),
        pytest.raises(RuntimeError, match="boom"),
    ):
        attached.map_partitions(fail, meta=attached._meta).compute(scheduler="sync")

    assert "Lifecycle error handler failed" in caplog.text


def test_failed_output_stays_silent_in_later_runs():
    events: list = []
    attached = _attach(_frame(), _counting_handlers(events))

    def fail(frame, partition_info=None):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        attached.map_partitions(fail, meta=attached._meta).compute(scheduler="sync")
    assert events[0] == "start"
    assert events[-1] == "error"
    events.clear()

    attached.compute(scheduler="sync")

    assert events == []


def test_attachment_cannot_be_pickled_for_remote_schedulers():
    attached = _attach(_frame(), _counting_handlers([]))

    with pytest.raises(TypeError, match="'sync' and 'threads'"):
        pickle.dumps(attached.expr.operand("kwargs")["lifecycle"])


def test_attach_restores_the_callback_dropped_by_runs_finishing_out_of_order():
    _attach(_frame(), _counting_handlers([]))
    lifecycle_callback = tap_module._callback._callback
    assert lifecycle_callback in Callback.active
    # What two overlapping local scheduler runs in two threads do to the global callbacks.
    run_a = local_callbacks()
    run_a.__enter__()
    run_b = local_callbacks()
    run_b.__enter__()
    run_a.__exit__(None, None, None)
    run_b.__exit__(None, None, None)
    assert lifecycle_callback not in Callback.active

    events: list = []
    _attach(_frame(), _counting_handlers(events)).compute(scheduler="sync")

    assert events[0] == "start"
    assert sorted(events[1:-1]) == [0, 1, 2, 3]
    assert events[-1] == "end"


class _SignallingCondition(threading.Condition):
    def __init__(self) -> None:
        super().__init__(threading.Lock())
        self.waiting = threading.Event()

    def wait(self, timeout=None):
        self.waiting.set()
        return super().wait(timeout)


def test_concurrent_copies_of_one_partition_are_handed_over_once():
    """A second copy of partition 0 waits for the first hand-over instead of repeating it."""
    entered = threading.Event()
    release = threading.Event()
    order: list[str] = []
    calls: list[int] = []

    def on_partition(_partition, part_no):
        calls.append(part_no)
        entered.set()
        assert release.wait(timeout=10)
        order.append("first copy delivered")

    attachment = _Attachment(OutputLifecycleHandlers(on_partition=on_partition), npartitions=1)
    condition = _SignallingCondition()
    attachment._condition = condition
    assert attachment.arm()
    attachment.start()
    partition = pd.DataFrame({"a": [1]})

    def second_copy():
        attachment.observe_partition(partition, {"number": 0})
        order.append("second copy returned")

    first = threading.Thread(
        target=attachment.observe_partition, args=(partition, {"number": 0})
    )
    first.start()
    assert entered.wait(timeout=10)
    second = threading.Thread(target=second_copy)
    second.start()
    assert condition.waiting.wait(timeout=10)
    release.set()
    first.join(timeout=10)
    second.join(timeout=10)

    assert calls == [0]
    assert order == ["first copy delivered", "second copy returned"]
