"""Lifecycle events on stock Dask: a pass-through tap on the output plus a scheduler callback.

How it works:

* ``attach_lifecycle`` wraps the output in a ``map_partitions`` pass-through ("tap") whose tasks
  are named ``("dvt-lifecycle-<attachment id>-<token>", i)``. The tap calls ``on_partition``
  inside the task (in the scheduler's worker thread), before any consumer sees the partition,
  and returns the partition unchanged.
* One process-wide ``dask.callbacks.Callback``, registered by every attach, observes every
  local scheduler run, whatever starts it (``compute()``, ``dask.compute`` of several
  collections or of delayed tasks), so no compute entrypoint has to activate it. For a run it
  decides, per attached output, whether the run produces the *whole* output: the run's graph
  must hold one tap expression of that output with exactly the partitions ``0..n-1`` declared
  at attach time. Only such runs are "armed" for that output; other runs (``head``, ``tail``,
  ``partitions[...]``, pruned graphs) leave it silent, including ``on_partition``.
* In an armed run the output owns its tap tasks and their ancestors up to other outputs' taps.
  The first owned task to start fires ``on_start``; the last tap task to finish fires ``on_end``;
  a failed run fires ``on_error`` for armed outputs that started and did not end.
* Lifecycle is one-shot per attachment: start, end and error are delivered at most once, and
  end/error are terminal; each partition number reaches ``on_partition`` at most once. Later
  runs (nested quantile passes of ``sort_values``/``set_index``, other sinks reading the same
  output) recompute the output silently.
* Runs started inside ``suppress_lifecycle_events()`` are ignored entirely (DVT reads graph
  metadata there).
* Fused tasks hide the tap keys: ``compute()`` does not fuse, default ``to_delayed()`` and
  ``persist()`` do, hence ``delayed_partitions``.
* Runs must not overlap across threads. A local scheduler run takes the global callbacks out
  of ``Callback.active`` until it finishes (``dask.callbacks.local_callbacks``): a run started
  in another thread meanwhile reports nothing, and overlapping runs that finish out of order
  leave the callback unregistered until the next attach. Nested runs inside a run's tasks
  stay silent by the same rule.

Private Dask touch points (checked by tests in ``tests/unit/core/dask_lifecycle``):
``MapPartitions`` (subclassed to keep ``unique_partition_mapping_columns_from_shuffle`` and to
keep the ``tune`` stage out of the output's subtree even when ``tune`` is switched on, so the
output keeps the partition count declared at attach time), ``Expr.rewrite``, task keys of a
``map_partitions`` expression being ``(f"{token}-{hash}", i)``, scheduler
``state["dependencies"]``, ``is_dask_collection`` accepting any expression, and
``Callback.active`` being swapped out for the duration of a run.
"""

from __future__ import annotations

import contextvars
import functools
import logging
import threading
import uuid
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from dask.callbacks import Callback
from dask.dataframe.dask_expr._collection import new_collection
from dask.dataframe.dask_expr._expr import MapPartitions

from core.dask_lifecycle.handlers import OutputLifecycleHandlers

logger = logging.getLogger(__name__)

_TOKEN_PREFIX = "dvt-lifecycle-"

_IDLE = "idle"
_STARTED = "started"
_ENDED = "ended"
_FAILED = "failed"

_suppressed_runs: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "dvt_dask_lifecycle_suppressed",
    default=False,
)


class LifecycleTapExpr(MapPartitions):
    """Pass-through ``MapPartitions`` that is transparent for partitioning knowledge."""

    @functools.cached_property
    def unique_partition_mapping_columns_from_shuffle(self):
        return self.frame.unique_partition_mapping_columns_from_shuffle

    def rewrite(self, kind: str, rewritten):
        if kind == "tune":
            # The output keeps the partitioning (and partition count) declared at attach time,
            # which the tap and the dataframe cache writer count on.
            return self
        return super().rewrite(kind, rewritten)


class _Attachment:
    __slots__ = (
        "__weakref__",
        "_condition",
        "_delivered",
        "_delivering",
        "_state",
        "armed_runs",
        "handlers",
        "id",
        "npartitions",
    )

    def __init__(self, handlers: OutputLifecycleHandlers, npartitions: int) -> None:
        self.id = uuid.uuid4().hex
        self.handlers = handlers
        self.npartitions = npartitions
        self.armed_runs = 0
        self._state = _IDLE
        self._condition = threading.Condition(threading.Lock())
        # Partition numbers handed to on_partition, and the ones being handed over right now
        # (number -> thread ident).
        self._delivered: set[int] = set()
        self._delivering: dict[int, int] = {}

    def __dask_tokenize__(self):
        return ("dvt-lifecycle-attachment", self.id)

    def __reduce__(self):
        raise TypeError(
            "DVT lifecycle taps support only local 'sync' and 'threads' Dask schedulers"
        )

    @property
    def terminal(self) -> bool:
        return self._state in (_ENDED, _FAILED)

    def arm(self) -> bool:
        with self._condition:
            if self._state in (_ENDED, _FAILED):
                return False
            self.armed_runs += 1
            return True

    def disarm(self) -> None:
        with self._condition:
            self.armed_runs -= 1

    def _accepts_partitions(self) -> bool:
        # A copy of a partition computed outside the output's own tasks may run before on_start;
        # it is skipped, and the visible tap task (which starts the output) delivers it.
        return self.armed_runs > 0 and self._state == _STARTED

    def observe_partition(self, partition, partition_info) -> None:
        on_partition = self.handlers.on_partition
        if on_partition is None:
            return
        number = partition_info.get("number") if partition_info else None
        if not isinstance(number, int):
            number = None
        me = threading.get_ident()
        with self._condition:
            if not self._accepts_partitions():
                return
            if number is not None:
                # Dask may compute one output partition more than once in a run (a copy fused
                # into a consumer task next to the visible tap task). Each number is handed
                # over once, and a tap task returns only after its number was handed over, so
                # the last tap task finishing still means "every partition delivered".
                while number in self._delivering:
                    if self._delivering[number] == me:
                        return
                    self._condition.wait()
                if number in self._delivered or not self._accepts_partitions():
                    return
                self._delivering[number] = me
        if number is None:
            on_partition(partition, None)
            return
        delivered = False
        try:
            on_partition(partition, number)
            delivered = True
        finally:
            with self._condition:
                del self._delivering[number]
                if delivered:
                    self._delivered.add(number)
                self._condition.notify_all()

    def start(self) -> None:
        with self._condition:
            if self._state != _IDLE:
                return
            self._state = _STARTED
        if self.handlers.on_start is not None:
            self.handlers.on_start()

    def end(self) -> None:
        with self._condition:
            if self._state != _STARTED:
                return
            self._state = _ENDED
        if self.handlers.on_end is not None:
            self.handlers.on_end()

    def fail(self) -> None:
        with self._condition:
            if self._state != _STARTED:
                return
            self._state = _FAILED
        if self.handlers.on_error is not None:
            self.handlers.on_error()


def _lifecycle_tap(partition, partition_info=None, lifecycle=None):
    lifecycle.observe_partition(partition, partition_info)
    return partition


def _attachment_id(key) -> str | None:
    if not isinstance(key, tuple) or len(key) != 2:
        return None
    name = key[0]
    if not isinstance(name, str) or not name.startswith(_TOKEN_PREFIX):
        return None
    return name[len(_TOKEN_PREFIX):].split("-", 1)[0]


@dataclass
class _Run:
    state: dict
    attachments: dict[str, _Attachment]
    owner: dict[Any, str]
    tap_owner: dict[Any, str]
    remaining: dict[str, set]
    started: set[str] = field(default_factory=set)


class _LifecycleCallback(Callback):
    def __init__(self, registry: weakref.WeakValueDictionary) -> None:
        super().__init__()
        self._registry = registry
        self._runs: dict[int, _Run] = {}
        self._runs_lock = threading.Lock()

    def _start_state(self, dsk, state) -> None:
        if not self._registry or _suppressed_runs.get():
            return

        taps: dict[str, dict[str, set]] = {}
        for key in dsk:
            attachment_id = _attachment_id(key)
            if attachment_id is not None:
                taps.setdefault(attachment_id, {}).setdefault(key[0], set()).add(key)
        if not taps:
            return

        boundaries = {key for names in taps.values() for keys in names.values() for key in keys}
        armed: dict[str, _Attachment] = {}
        tap_owner: dict[Any, str] = {}
        remaining: dict[str, set] = {}
        for attachment_id, names in taps.items():
            attachment = self._registry.get(attachment_id)
            if attachment is None or attachment.terminal:
                continue
            if not _produces_whole_output(attachment, names):
                continue
            if not attachment.arm():
                continue
            armed[attachment_id] = attachment
            (keys,) = names.values()
            remaining[attachment_id] = set(keys)
            tap_owner.update(dict.fromkeys(keys, attachment_id))
        if not armed:
            return

        dependencies = state["dependencies"]
        owner: dict[Any, str] = {}
        for attachment_id, keys in remaining.items():
            stack = list(keys)
            while stack:
                key = stack.pop()
                if key in owner:
                    continue
                owner[key] = attachment_id
                stack.extend(
                    dep
                    for dep in dependencies.get(key, ())
                    if dep not in boundaries and dep not in owner
                )

        with self._runs_lock:
            self._runs[id(state)] = _Run(
                state=state,
                attachments=armed,
                owner=owner,
                tap_owner=tap_owner,
                remaining=remaining,
            )

    def _pretask(self, key, _dsk, state) -> None:
        run = self._runs.get(id(state))
        if run is None:
            return
        attachment_id = run.owner.get(key)
        if attachment_id is None or attachment_id in run.started:
            return
        run.started.add(attachment_id)
        run.attachments[attachment_id].start()

    def _posttask(self, key, _result, _dsk, state, _worker_id) -> None:
        run = self._runs.get(id(state))
        if run is None:
            return
        attachment_id = run.tap_owner.get(key)
        if attachment_id is None:
            return
        remaining = run.remaining[attachment_id]
        remaining.discard(key)
        if not remaining:
            run.attachments[attachment_id].end()

    def _finish(self, _dsk, state, errored) -> None:
        with self._runs_lock:
            run = self._runs.pop(id(state), None)
        if run is None:
            return
        for attachment in run.attachments.values():
            attachment.disarm()
        if not errored:
            return
        for attachment_id in run.started:
            try:
                run.attachments[attachment_id].fail()
            except Exception:
                # Do not mask the error that failed the computation.
                logger.exception("Lifecycle error handler failed for output %s", attachment_id)


def _produces_whole_output(attachment: _Attachment, names: dict[str, set]) -> bool:
    if len(names) != 1:
        # Several renamed copies of one output in one graph (e.g. a full and a pruned one):
        # partition numbers cannot be trusted, so stay silent.
        return False
    (keys,) = names.values()
    numbers = {key[1] for key in keys}
    expected = set(range(attachment.npartitions))
    if numbers == expected:
        return True
    if not numbers <= expected:
        logger.warning(
            "Dask run produces partitions %s of an output declared with %s partitions; "
            "lifecycle events for it are skipped",
            sorted(numbers - expected)[:5],
            attachment.npartitions,
        )
    return False


_registry: weakref.WeakValueDictionary[str, _Attachment] = weakref.WeakValueDictionary()
_callback = _LifecycleCallback(_registry)


def attach_lifecycle(frame, handlers: OutputLifecycleHandlers):
    """Attach ``handlers`` to a DataFrame output; return the DataFrame to hand downstream.

    Every call is a separate attachment with its own one-shot lifecycle.
    """
    if handlers.is_empty():
        return frame
    with suppress_lifecycle_events():
        npartitions = frame.npartitions
    attachment = _Attachment(handlers, npartitions)
    plain = frame.map_partitions(
        _lifecycle_tap,
        lifecycle=attachment,
        meta=frame._meta,
        enforce_metadata=False,
        transform_divisions=False,
        align_dataframes=False,
        token=f"{_TOKEN_PREFIX}{attachment.id}",
    )
    if type(plain.expr) is not MapPartitions:
        raise RuntimeError(
            f"Unexpected expression for a lifecycle tap: {type(plain.expr).__name__}"
        )
    tapped = new_collection(LifecycleTapExpr(*plain.expr.operands))
    _registry[attachment.id] = attachment
    # Idempotent (a set add); repeated so a registration lost to overlapping runs comes back.
    _callback.register()
    return tapped


def delayed_partitions(frame) -> list:
    """``frame.to_delayed()`` as a flat list whose computation still reports lifecycle events.

    Default ``to_delayed()`` fuses tasks, and the tap keys disappear inside fused tasks.
    """
    return list(frame.optimize(fuse=False).to_delayed(optimize_graph=False))


@contextmanager
def suppress_lifecycle_events() -> Iterator[None]:
    """Report nothing for Dask runs started inside the block in this context.

    Used while DVT reads graph metadata (``npartitions``, ``divisions``) of a node output:
    that can run a nested Dask computation (``sort_values``/``set_index`` quantiles) which is
    graph building, not the execution of the upstream nodes.
    """
    token = _suppressed_runs.set(True)
    try:
        yield
    finally:
        _suppressed_runs.reset(token)
