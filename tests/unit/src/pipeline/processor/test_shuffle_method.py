"""The project's shuffle method decides how Dask shuffles inside one pipeline run.

The method is observed the way the 2026-11-19 benchmark observed it: which Dask shuffle class
built a graph layer during the run and how many ``partd.File`` objects were created (only the
disk shuffle creates them while it runs).
"""

import collections

import dask
import dask.dataframe as dd
import numpy as np
import pandas as pd
import partd
import pytest
from dask.dataframe.dask_expr import _shuffle
from tests.unit.src.pipeline.test_processor import _register_nodes

from src.node_dsl import DFOutputBaseNode, InputField, OutputField, SignalOutputBaseNode
from src.node_dsl.core.input_values import NodeInputConstantValue, NodeInputLinkValue
from src.nodes.transform.df_join import DataFrameJoin
from src.nodes.transform.df_set_index import DataFrameSetIndex
from src.nodes.transform.df_sort_values import DataFrameSortValues
from src.pipeline.processor import PipelineProcessor
from src.schemas.internal import NodeData, ProjectSettings, ProjectVariables, TaskInternal

SHUFFLE_METHOD_KEY = "dataframe.shuffle.method"
ROWS = 4_000


class ShuffleProbeSource(DFOutputBaseNode):
    seed: int = InputField(default=0)
    output: dd.DataFrame = OutputField()

    def process(self):
        rng = np.random.default_rng(self.seed)
        pdf = pd.DataFrame({"id": rng.permutation(ROWS), "value": rng.random(ROWS)})
        self.output = dd.from_pandas(pdf, npartitions=8, sort=False)


class ShuffleProbeSink(SignalOutputBaseNode):
    df: dd.DataFrame = InputField()
    rows: int | None = None

    def process(self):
        # Partition lengths, as the benchmark sink computes them: computing a sorted frame whole
        # lets Dask collapse it to one partition first and skip the shuffle.
        lengths = self.df.map_partitions(len, meta=(None, "int64"))
        type(self).rows = int(lengths.compute(scheduler="threads", num_workers=2).sum())


def _source(seed: int) -> NodeData:
    return NodeData(
        name="ShuffleProbeSource",
        inputs={"seed": NodeInputConstantValue(value=seed)},
    )


def _const(value) -> NodeInputConstantValue:
    return NodeInputConstantValue(value=value)


def _link(node_id: str) -> NodeInputLinkValue:
    return NodeInputLinkValue(node_id=node_id, output_name="output")


# One pipeline per shuffling node; each ends in a sink that computes the shuffled frame.
OPERATIONS = {
    "join": {
        "left": _source(1),
        "right": _source(2),
        "op": NodeData(
            name="DataFrameJoin",
            inputs={
                "left": _link("left"),
                "right": _link("right"),
                "left_on": _const(["id"]),
                "right_on": _const(["id"]),
                "how": _const("inner"),
            },
        ),
    },
    "sort_values": {
        "left": _source(1),
        "op": NodeData(
            name="DataFrameSortValues",
            inputs={"df": _link("left"), "by": _const(["value"])},
        ),
    },
    "set_index": {
        "left": _source(1),
        "op": NodeData(
            name="DataFrameSetIndex",
            inputs={"df": _link("left"), "index_col": _const("value")},
        ),
    },
}


@pytest.fixture
def shuffle_events(monkeypatch) -> collections.Counter:
    events: collections.Counter = collections.Counter()

    for cls in (_shuffle.DiskShuffle, _shuffle.TaskShuffle, _shuffle.P2PShuffle):
        original_layer = cls.__dict__["_layer"]

        def _layer(self, _original=original_layer, _name=cls.__name__):
            events[_name] += 1
            return _original(self)

        monkeypatch.setattr(cls, "_layer", _layer)

    original_file_init = partd.File.__init__

    def _file_init(self, *args, **kwargs):
        events["partd.File"] += 1
        return original_file_init(self, *args, **kwargs)

    monkeypatch.setattr(partd.File, "__init__", _file_init)
    _register_nodes(
        ShuffleProbeSource,
        ShuffleProbeSink,
        DataFrameJoin,
        DataFrameSortValues,
        DataFrameSetIndex,
    )
    ShuffleProbeSink.rows = None
    return events


def _task(operation: str, shuffle_method: str | None) -> TaskInternal:
    pipeline = {
        **OPERATIONS[operation],
        "sink": NodeData(name="ShuffleProbeSink", inputs={"df": _link("op")}),
    }
    return TaskInternal(
        project_id="project-shuffle-method",
        task_id=f"task-{operation}-{shuffle_method}",
        user_id="user-shuffle-method",
        pipeline=pipeline,
        target_nodes=["sink"],
        project_settings=ProjectSettings(
            store_enabled=False,
            ttl_time=0,
            workers_count=0,
            shuffle_method=shuffle_method,
        ),
        project_variables=ProjectVariables(variables={}),
    )


async def _run(task: TaskInternal) -> PipelineProcessor:
    processor = PipelineProcessor(task=task)
    result = await processor.process()
    assert result.success, result.error_message
    assert processor.failed_nodes == []
    return processor


def _used_method(events: collections.Counter) -> str:
    disk = events["DiskShuffle"] > 0 and events["partd.File"] > 0
    tasks = events["TaskShuffle"] > 0
    assert disk != tasks and events["P2PShuffle"] == 0, dict(events)
    if tasks:
        assert events["partd.File"] == 0, dict(events)
    return "disk" if disk else "tasks"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(OPERATIONS))
@pytest.mark.parametrize("shuffle_method", ["tasks", "disk"])
async def test_project_shuffle_method_selects_dask_shuffle_for_the_run(
    shuffle_events, operation, shuffle_method
):
    with dask.config.set({SHUFFLE_METHOD_KEY: None}):
        await _run(_task(operation, shuffle_method))

        assert _used_method(shuffle_events) == shuffle_method
        assert ShuffleProbeSink.rows == ROWS
        assert dask.config.get(SHUFFLE_METHOD_KEY, None) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("installation_default", "expected_method"),
    [(None, "disk"), ("tasks", "tasks")],
)
async def test_unset_project_shuffle_method_keeps_installation_default(
    shuffle_events, installation_default, expected_method
):
    # An installation default arrives through DASK_DATAFRAME__SHUFFLE__METHOD, i.e. the same
    # Dask config key the outer ``set`` stands in for here.
    with dask.config.set({SHUFFLE_METHOD_KEY: installation_default}):
        await _run(_task("join", None))

        assert _used_method(shuffle_events) == expected_method
        assert dask.config.get(SHUFFLE_METHOD_KEY, None) == installation_default


@pytest.mark.asyncio
async def test_project_shuffle_method_does_not_leak_into_next_run_in_same_process(shuffle_events):
    with dask.config.set({SHUFFLE_METHOD_KEY: None}):
        await _run(_task("sort_values", "tasks"))
        assert _used_method(shuffle_events) == "tasks"

        shuffle_events.clear()
        await _run(_task("sort_values", None))
        assert _used_method(shuffle_events) == "disk"


@pytest.mark.asyncio
async def test_project_shuffle_method_is_restored_when_the_run_raises(shuffle_events):
    def _fail_on_start(**_kwargs):
        raise RuntimeError("callback failed")

    with dask.config.set({SHUFFLE_METHOD_KEY: "disk"}):
        processor = PipelineProcessor(
            task=_task("join", "tasks"),
            on_task_started=_fail_on_start,
        )
        with pytest.raises(RuntimeError, match="callback failed"):
            await processor.process()

        assert dask.config.get(SHUFFLE_METHOD_KEY, None) == "disk"
