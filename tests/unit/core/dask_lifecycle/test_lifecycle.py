"""Behaviour of the node-output lifecycle seam (``core.dask_lifecycle``)."""

import itertools
import threading
from collections import Counter

import dask
import dask.dataframe as dd
import numpy as np
import pandas as pd
import pytest
from dask import delayed

import core.dask_lifecycle as lifecycle
from core.dask_lifecycle import OutputLifecycleHandlers

_seeds = itertools.count(1)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, int | None, pd.DataFrame | None]] = []
        self._lock = threading.Lock()

    def handlers(self, name: str) -> OutputLifecycleHandlers:
        def record(kind, part_no=None, partition=None):
            with self._lock:
                self.events.append((kind, name, part_no, partition))

        return OutputLifecycleHandlers(
            on_start=lambda: record("start"),
            on_end=lambda: record("end"),
            on_error=lambda: record("error"),
            on_partition=lambda partition, part_no: record("partition", part_no, partition),
        )

    def counts(self, name: str) -> dict[str, int]:
        counter = Counter(kind for kind, owner, _, _ in self.events if owner == name)
        return {kind: counter[kind] for kind in ("start", "partition", "end", "error")}

    def part_numbers(self, name: str) -> list[int]:
        return sorted(
            part_no
            for kind, owner, part_no, _ in self.events
            if owner == name and kind == "partition"
        )

    def partitions(self, name: str) -> list[pd.DataFrame]:
        """Delivered partitions in partition-number order."""
        numbered = [
            (part_no, partition)
            for kind, owner, part_no, partition in self.events
            if owner == name and kind == "partition"
        ]
        return [partition for _, partition in sorted(numbered, key=lambda item: item[0])]

    def kinds(self, name: str) -> list[str]:
        return [kind for kind, owner, _, _ in self.events if owner == name]


def _attach(frame, recorder: _Recorder, name: str):
    return lifecycle.attach_lifecycle(frame, recorder.handlers(name))


def _once(npartitions: int) -> dict[str, int]:
    return {"start": 1, "partition": npartitions, "end": 1, "error": 0}


def _left_right() -> tuple[pd.DataFrame, pd.DataFrame]:
    # A fresh seed per test keeps Dask expression names unique across tests.
    rng = np.random.default_rng(next(_seeds))
    left = pd.DataFrame({"k": rng.integers(0, 50, 400), "a": rng.random(400)})
    right = pd.DataFrame({"k": np.arange(50), "b": rng.random(50)})
    return left, right


def _sorted_frame(frame: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    return frame.sort_values(by).reset_index(drop=True)


@pytest.mark.parametrize(
    ("scheduler", "npartitions"),
    [("sync", 4), ("threads", 16)],
)
def test_full_compute_reports_start_every_partition_and_end_once(scheduler, npartitions):
    left, _ = _left_right()
    recorder = _Recorder()
    a = _attach(dd.from_pandas(left, npartitions=npartitions), recorder, "A")
    b = _attach(a.assign(x=a.a * 2), recorder, "B")

    result = b.compute(scheduler=scheduler)

    pd.testing.assert_frame_equal(result, left.assign(x=left.a * 2))
    for name in ("A", "B"):
        assert recorder.counts(name) == _once(npartitions)
        assert recorder.part_numbers(name) == list(range(npartitions))
        kinds = recorder.kinds(name)
        assert kinds[0] == "start"
        assert kinds[-1] == "end"


def test_cache_writer_like_consumer_sees_every_partition_before_end():
    left, _ = _left_right()
    npartitions = 32

    class _Consumer:
        def __init__(self) -> None:
            self.lock = threading.Lock()
            self.started = False
            self.rows: dict[int, int] = {}
            self.duplicates = 0
            self.after_end = 0
            self.rows_at_end: dict[int, int] | None = None
            self.active = 0
            self.max_active = 0

        def start(self) -> None:
            self.started = True

        def partition(self, partition: pd.DataFrame, part_no: int | None) -> None:
            with self.lock:
                assert self.started
                if self.rows_at_end is not None:
                    self.after_end += 1
                if part_no in self.rows:
                    self.duplicates += 1
                self.rows[part_no] = len(partition)
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            partition.to_numpy().sum()  # some work outside the lock
            with self.lock:
                self.active -= 1

        def end(self) -> None:
            with self.lock:
                self.rows_at_end = dict(self.rows)

    consumer = _Consumer()
    attached = lifecycle.attach_lifecycle(
        dd.from_pandas(left, npartitions=npartitions),
        OutputLifecycleHandlers(
            on_start=consumer.start,
            on_end=consumer.end,
            on_partition=consumer.partition,
        ),
    )

    result = attached.compute(scheduler="threads", num_workers=8)

    assert len(result) == len(left)
    assert consumer.rows_at_end is not None
    assert sorted(consumer.rows_at_end) == list(range(npartitions))
    assert sum(consumer.rows_at_end.values()) == len(left)
    assert consumer.duplicates == 0
    assert consumer.after_end == 0


def test_join_then_sort_values_reports_each_node_once():
    left, right = _left_right()
    recorder = _Recorder()
    a = _attach(dd.from_pandas(left, npartitions=4), recorder, "A")
    b = _attach(dd.from_pandas(right, npartitions=1), recorder, "B")
    joined = _attach(a.merge(b, on="k", how="inner").assign(x=lambda d: d.a + d.b), recorder, "J")

    result = joined.sort_values("x").compute(scheduler="threads")

    expected = left.merge(right, on="k", how="inner").assign(x=lambda d: d.a + d.b)
    assert result["x"].tolist() == sorted(expected["x"].tolist())
    assert recorder.counts("A") == _once(4)
    assert recorder.counts("B") == _once(1)
    assert recorder.counts("J") == _once(4)
    # J's partitions are delivered whole (all columns), even when the first complete run is
    # the nested quantile pass of sort_values.
    delivered = pd.concat(recorder.partitions("J"))
    pd.testing.assert_frame_equal(
        _sorted_frame(delivered, ["x"]), _sorted_frame(expected, ["x"]), check_dtype=False
    )


def test_join_then_set_index():
    left, right = _left_right()
    recorder = _Recorder()
    a = _attach(dd.from_pandas(left, npartitions=4), recorder, "A")
    b = _attach(dd.from_pandas(right, npartitions=1), recorder, "B")
    joined = _attach(a.merge(b, on="k", how="inner").assign(x=lambda d: d.a + d.b), recorder, "J")

    result = joined.set_index("x").compute(scheduler="threads")

    expected = left.merge(right, on="k", how="inner").assign(x=lambda d: d.a + d.b)
    assert result.index.tolist() == sorted(expected["x"].tolist())
    # set_index runs three Dask passes; each output reports once.
    assert recorder.counts("A") == _once(4)
    assert recorder.counts("B") == _once(1)
    assert recorder.counts("J") == _once(4)


_UNLOWERED_OUTPUTS = {
    "merge": lambda a, b: a.merge(b, on="k", how="inner"),
    "sort_values": lambda a, _b: a.sort_values("a"),
    "set_index": lambda a, _b: a.set_index("a"),
    "groupby": lambda a, _b: a.groupby("k").a.sum().to_frame(),
}


@pytest.mark.parametrize("shape", sorted(_UNLOWERED_OUTPUTS))
def test_map_partitions_downstream_of_an_output_that_needs_lowering(shape):
    """A consumer applies ``map_partitions`` to an output whose expression is not lowered yet."""
    left, right = _left_right()
    recorder = _Recorder()
    a = dd.from_pandas(left, npartitions=4)
    b = dd.from_pandas(right, npartitions=1)
    output = _UNLOWERED_OUTPUTS[shape](a, b)
    with lifecycle.suppress_lifecycle_events():
        npartitions = output.npartitions
    attached = _attach(output, recorder, "O")

    rows = attached.map_partitions(len, meta=(None, "int64")).compute(scheduler="threads")

    assert int(rows.sum()) == len(_UNLOWERED_OUTPUTS[shape](left, right))
    assert recorder.counts("O") == _once(npartitions)


def test_sorted_output_metadata_read_while_suppressed_then_full_compute():
    left, _ = _left_right()
    recorder = _Recorder()
    a = _attach(dd.from_pandas(left, npartitions=4), recorder, "A")
    sorted_frame = a.sort_values("a")

    # DVT reads npartitions/divisions of an output while building the graph; for a sort this
    # runs a nested quantile computation.
    with lifecycle.suppress_lifecycle_events():
        npartitions = sorted_frame.npartitions
        divisions = sorted_frame.divisions
    assert recorder.events == []

    s = _attach(sorted_frame, recorder, "S")
    assert s.npartitions == npartitions
    assert s.divisions == divisions
    assert recorder.events == []

    result = s.compute(scheduler="threads")

    assert result["a"].tolist() == sorted(left["a"].tolist())
    assert recorder.counts("A") == _once(4)
    assert recorder.counts("S") == _once(npartitions)
    assert recorder.part_numbers("S") == list(range(npartitions))
    delivered = pd.concat(recorder.partitions("S"))
    assert delivered["a"].tolist() == sorted(left["a"].tolist())


def test_repartition_by_size_metadata_read_while_suppressed_then_full_compute():
    rng = np.random.default_rng(next(_seeds))
    pdf = pd.DataFrame({"t": rng.random(400), "a": rng.random(400)})
    recorder = _Recorder()
    a = _attach(dd.from_pandas(pdf, npartitions=4), recorder, "A")
    resized = a.repartition(partition_size="2kB")

    with lifecycle.suppress_lifecycle_events():
        resized.npartitions  # noqa: B018 - computes partition sizes, as DVT's execute does

    assert recorder.events == []

    result = resized.compute(scheduler="threads")

    pd.testing.assert_frame_equal(result, pdf)
    assert recorder.counts("A") == _once(4)


def test_merge_asof_reports_each_source_once():
    rng = np.random.default_rng(next(_seeds))
    left = pd.DataFrame({"t": np.sort(rng.random(400)), "a": rng.random(400)})
    right = pd.DataFrame({"t": np.sort(rng.random(100)), "b": rng.random(100)})
    recorder = _Recorder()
    a = _attach(dd.from_pandas(left, npartitions=4, sort=False), recorder, "L")
    b = _attach(dd.from_pandas(right, npartitions=2, sort=False), recorder, "R")

    result = dd.merge_asof(a, b, on="t").compute(scheduler="threads")

    pd.testing.assert_frame_equal(
        result.reset_index(drop=True), pd.merge_asof(left, right, on="t")
    )
    assert recorder.counts("L") == _once(4)
    assert recorder.counts("R") == _once(2)


def test_partial_computes_are_silent_then_full_compute_reports_once():
    left, _ = _left_right()
    recorder = _Recorder()
    a = _attach(dd.from_pandas(left, npartitions=4), recorder, "A")
    b = _attach(a.assign(x=a.a * 2), recorder, "B")

    b.head(2)
    b.tail(2)
    b.partitions[1].compute()
    b.optimize().partitions[:2].compute()
    assert recorder.events == []

    b.compute()

    assert recorder.counts("A") == _once(4)
    assert recorder.counts("B") == _once(4)


def test_second_full_compute_of_the_same_output_is_silent():
    left, _ = _left_right()
    recorder = _Recorder()
    a = _attach(dd.from_pandas(left, npartitions=4), recorder, "A")

    a.compute()
    a.compute()

    # One-shot per attached output.
    assert recorder.counts("A") == _once(4)


def test_error_in_upstream_node():
    left, _ = _left_right()
    recorder = _Recorder()
    a = _attach(dd.from_pandas(left, npartitions=4), recorder, "A")
    b = _attach(a.assign(x=a.a * 2), recorder, "B")

    def fail_on_third(frame, partition_info=None):
        if partition_info["number"] == 2:
            raise RuntimeError("boom")
        return frame

    c = _attach(b.map_partitions(fail_on_third, meta=b._meta), recorder, "C")
    d = _attach(c.assign(z=1), recorder, "D")

    with pytest.raises(RuntimeError, match="boom"):
        d.compute(scheduler="sync")

    for name in ("A", "B", "C", "D"):
        counts = recorder.counts(name)
        assert counts["start"] == 1
        assert counts["end"] == 0
    # Every output that started and did not end gets on_error once.
    assert [recorder.counts(name)["error"] for name in ("A", "B", "C", "D")] == [1, 1, 1, 1]


def test_delayed_partitions_with_dask_compute():
    left, _ = _left_right()
    recorder = _Recorder()
    a = _attach(dd.from_pandas(left, npartitions=4), recorder, "A")
    b = _attach(a.assign(x=a.a * 2), recorder, "B")

    parts = lifecycle.delayed_partitions(b)
    assert len(parts) == b.npartitions
    results = dask.compute(*[delayed(lambda part: part)(part) for part in parts])

    pd.testing.assert_frame_equal(pd.concat(results), left.assign(x=left.a * 2))
    assert recorder.counts("A") == _once(4)
    assert recorder.counts("B") == _once(4)


def test_delayed_partitions_mixed_with_a_reduction_in_one_compute():
    """Like the global first/last aggregation: delayed partitions next to a dask-expr reduction.

    Dask fuses a copy of the output into the reduction's tasks here, so the output is computed
    twice in one run.
    """
    left, _ = _left_right()
    recorder = _Recorder()
    a = _attach(dd.from_pandas(left, npartitions=4), recorder, "A")
    series = a["a"]

    first = delayed(lambda parts: parts[0].iloc[0])(lifecycle.delayed_partitions(series))
    first_value, total = dask.compute(first, series.sum(), scheduler="threads")

    assert first_value == left["a"].iloc[0]
    assert total == pytest.approx(left["a"].sum())
    assert recorder.counts("A") == _once(4)
    assert recorder.part_numbers("A") == [0, 1, 2, 3]
    assert recorder.kinds("A")[0] == "start"
    assert recorder.kinds("A")[-1] == "end"


def test_two_outputs_sharing_an_upstream_in_one_compute():
    left, _ = _left_right()
    recorder = _Recorder()
    a = _attach(dd.from_pandas(left, npartitions=4), recorder, "A")
    b1 = _attach(a.assign(x=a.a * 2), recorder, "B1")
    b2 = _attach(a.assign(y=a.a * 3), recorder, "B2")

    r1, r2 = dask.compute(b1, b2, scheduler="threads")

    pd.testing.assert_frame_equal(r1, left.assign(x=left.a * 2))
    pd.testing.assert_frame_equal(r2, left.assign(y=left.a * 3))
    for name in ("A", "B1", "B2"):
        assert recorder.counts(name) == _once(4)


def test_two_outputs_sharing_an_upstream_in_separate_computes():
    left, _ = _left_right()
    recorder = _Recorder()
    a = _attach(dd.from_pandas(left, npartitions=4), recorder, "A")
    b1 = _attach(a.assign(x=a.a * 2), recorder, "B1")
    b2 = _attach(a.assign(y=a.a * 3), recorder, "B2")

    b1.compute(scheduler="threads")
    b2.compute(scheduler="threads")

    assert recorder.counts("B1") == _once(4)
    assert recorder.counts("B2") == _once(4)
    assert recorder.counts("A") == _once(4)


def test_len_and_projection_after_an_output():
    left, _ = _left_right()
    recorder = _Recorder()
    a = _attach(dd.from_pandas(left, npartitions=4), recorder, "A")
    b = _attach(a.assign(x=a.a * 2), recorder, "B")
    a2 = _attach(dd.from_pandas(left, npartitions=4), recorder, "A2")
    b2 = _attach(a2.assign(x=a2.a * 2), recorder, "B2")

    assert len(b) == len(left)
    projected = b2[["x"]].compute()

    pd.testing.assert_frame_equal(projected, left.assign(x=left.a * 2)[["x"]])
    for name in ("A", "B", "A2", "B2"):
        assert recorder.counts(name) == _once(4)


def test_shuffle_partitioning_knowledge_survives_attach():
    left, _ = _left_right()
    recorder = _Recorder()
    shuffled = dd.from_pandas(left, npartitions=4).shuffle("k")
    expected = shuffled.expr.unique_partition_mapping_columns_from_shuffle
    assert expected

    attached = _attach(shuffled, recorder, "S")

    assert attached.expr.unique_partition_mapping_columns_from_shuffle == expected
    assert attached.assign(z=1).expr.unique_partition_mapping_columns_from_shuffle == expected


def test_divisions_meta_index_and_row_order_survive_attach():
    rng = np.random.default_rng(next(_seeds))
    pdf = pd.DataFrame(
        {
            "a": rng.random(100),
            "s": pd.Series([f"v{i}" for i in range(100)], dtype="string"),
            "c": pd.Categorical(rng.choice(["x", "y"], 100)),
        },
        index=pd.Index(np.arange(100) * 3, name="row_id"),
    )
    frame = dd.from_pandas(pdf, npartitions=5)
    unknown = frame.clear_divisions()
    recorder = _Recorder()

    attached = _attach(frame, recorder, "F")
    attached_unknown = _attach(unknown, recorder, "U")

    assert attached.known_divisions
    assert attached.divisions == frame.divisions
    assert attached.npartitions == frame.npartitions
    assert not attached_unknown.known_divisions
    assert attached_unknown.divisions == unknown.divisions
    pd.testing.assert_frame_equal(attached._meta, frame._meta)
    assert attached.index.name == "row_id"
    assert attached.dtypes.to_dict() == frame.dtypes.to_dict()
    pd.testing.assert_frame_equal(attached.compute(), pdf)
    pd.testing.assert_frame_equal(attached.loc[30:60].compute(), pdf.loc[30:60])


def test_physical_index_bookkeeping_survives_attach():
    dataframe_index = pytest.importorskip("core.utils.dataframe_index")
    from core.types.dataframe_index import PhysicalDataFrameIndex

    name = "__dvt_partition_key"
    descriptor = PhysicalDataFrameIndex(
        name=name, strategy="range", source_column="id", bound_column="id"
    )
    pdf = pd.DataFrame({"id": np.arange(20), "value": np.arange(20)})
    frame = dataframe_index.set_physical_index(
        dd.from_pandas(pdf.set_index("id", drop=False).rename_axis(name), npartitions=4),
        descriptor,
    )

    attached = _attach(frame, _Recorder(), "P")

    carried = dataframe_index.carry_physical_index(frame, attached)
    assert dataframe_index.get_physical_index(carried) == descriptor
    assert carried.divisions == frame.divisions


def _grouped_200_partitions() -> tuple[pd.DataFrame, dd.DataFrame]:
    rng = np.random.default_rng(next(_seeds))
    pdf = pd.DataFrame({"k": rng.integers(0, 7, 2000), "v": rng.random(2000)})
    return pdf, dd.from_pandas(pdf, npartitions=200).groupby("k").v.sum().to_frame()


def test_tune_is_off_by_default_once_the_package_is_imported():
    _, grouped = _grouped_200_partitions()

    assert dask.config.get("optimization.tune.active") is False
    assert grouped.optimize().npartitions == grouped.npartitions == 1


def test_attached_output_keeps_its_partition_count_when_tune_is_on():
    pdf, grouped = _grouped_200_partitions()

    with dask.config.set({"optimization.tune.active": True}):
        # Without lifecycle handlers Dask's `tune` stage re-plans the aggregation.
        assert grouped.optimize().npartitions != grouped.npartitions

        recorder = _Recorder()
        attached = _attach(grouped, recorder, "G")

        assert attached.optimize().npartitions == grouped.npartitions == 1
        pd.testing.assert_frame_equal(
            attached.compute().sort_index(), pdf.groupby("k").v.sum().to_frame()
        )
    assert recorder.counts("G") == _once(1)


def test_empty_handlers_return_the_frame_unchanged():
    frame = dd.from_pandas(pd.DataFrame({"a": [1, 2, 3]}), npartitions=2)

    attached = lifecycle.attach_lifecycle(frame, OutputLifecycleHandlers())

    assert attached is frame
