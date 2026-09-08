from typing import Any

import dask.dataframe as dd
import pandas as pd
import pytest

from src.node_dsl import (
    DFOutputBaseNode,
    InputField,
    OutputField,
    get_all_node_packages,
)
from src.node_dsl.node_typing import IO
from src.pipeline.execution_mode import PipelineExecutionMode


class _BeforeNeighborNode(DFOutputBaseNode):
    df_in: dd.DataFrame = InputField()
    output: dd.DataFrame = OutputField()

    def process(self) -> None:
        # Ensure a real transformation branch with operation callbacks.
        self.output = self.df_in.assign(__before_tmp=self.df_in["value"] * 2).drop(columns="__before_tmp")


class _AfterNeighborNode(DFOutputBaseNode):
    df_in: dd.DataFrame = InputField()
    output: dd.DataFrame = OutputField()

    def process(self) -> None:
        # Ensure a real transformation branch with operation callbacks.
        self.output = self.df_in.assign(__after_tmp=self.df_in["value"] + 3).drop(columns="__after_tmp")


def _discover_df_output_node_classes() -> tuple[type[DFOutputBaseNode], ...]:
    discovered = [
        descriptor.node_cls
        for descriptor in get_all_node_packages().values()
        if issubclass(descriptor.node_cls, DFOutputBaseNode)
        and descriptor.node_cls is not DFOutputBaseNode
        and any(
            field.resolved_type in {IO.DATAFRAME, IO.COLUMN}
            for field in descriptor.node_cls.output_fields().values()
        )
    ]
    return tuple(
        sorted(
            discovered,
            key=lambda cls: (cls.__module__, cls.__name__),
        )
    )

def _first_dask_output_name(node_cls: type[DFOutputBaseNode]) -> str:
    for field in node_cls.output_fields().values():
        if field.resolved_type in {IO.DATAFRAME, IO.COLUMN}:
            return field.attr_name
    raise AssertionError(
        f"{node_cls.__module__}.{node_cls.__name__} has no Dask DATAFRAME/COLUMN output field"
    )


def _empty_events() -> dict[str, Any]:
    return {
        "started": 0,
        "finished": 0,
        "progress_calls": 0,
        "node_ids": set(),
    }


def _build_callbacks(events: dict[str, Any], callback_events: list[tuple[str, str]]):
    def _on_start(*, node, **_kwargs) -> None:
        events["started"] += 1
        events["node_ids"].add(node.node_id)
        callback_events.append(("start", node.node_id))

    def _on_success(*, node, **_kwargs) -> None:
        events["finished"] += 1
        events["node_ids"].add(node.node_id)
        callback_events.append(("finish", node.node_id))

    def _on_progress(*, node, **_kwargs) -> None:
        events["progress_calls"] += 1
        events["node_ids"].add(node.node_id)
        callback_events.append(("progress", node.node_id))

    return _on_start, _on_success, _on_progress


DF_OUTPUT_NODE_CLASSES = _discover_df_output_node_classes()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "node_cls",
    DF_OUTPUT_NODE_CLASSES,
    ids=lambda cls: f"{cls.__module__}.{cls.__name__}",
)
async def test_df_output_callbacks_are_bound_to_target_node(
        node_cls: type[DFOutputBaseNode],
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_ddf = dd.from_pandas(pd.DataFrame({"value": [1, 2, 3, 4]}), npartitions=2)
    callback_events: list[tuple[str, str]] = []

    before_events = _empty_events()
    target_events = _empty_events()
    after_events = _empty_events()

    before_callbacks = _build_callbacks(before_events, callback_events)
    target_callbacks = _build_callbacks(target_events, callback_events)
    after_callbacks = _build_callbacks(after_events, callback_events)

    before_node = _BeforeNeighborNode(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="before_node",
        df_in=source_ddf,
        on_process_start=before_callbacks[0],
        on_process_success=before_callbacks[1],
        on_progress_step=before_callbacks[2],
    )
    await before_node.execute(PipelineExecutionMode.FULL)

    target_output_name = _first_dask_output_name(node_cls)

    def _patched_target_process(self: DFOutputBaseNode) -> None:
        upstream_ddf = getattr(self, "_test_upstream_ddf")
        setattr(
            self,
            target_output_name,
            upstream_ddf.assign(__target_tmp=upstream_ddf["value"] + 1).drop(columns="__target_tmp"),
        )

    monkeypatch.setattr(node_cls, "process", _patched_target_process)

    target_node = node_cls(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="target_node",
        on_process_start=target_callbacks[0],
        on_process_success=target_callbacks[1],
        on_progress_step=target_callbacks[2],
    )
    setattr(target_node, "_test_upstream_ddf", before_node.output)
    await target_node.execute(PipelineExecutionMode.FULL)

    after_node = _AfterNeighborNode(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="after_node",
        df_in=getattr(target_node, target_output_name),
        on_process_start=after_callbacks[0],
        on_process_success=after_callbacks[1],
        on_progress_step=after_callbacks[2],
    )
    await after_node.execute(PipelineExecutionMode.FULL)

    before_computed = before_node.output.compute(scheduler="threads")
    assert len(before_computed) == 4

    target_computed = getattr(target_node, target_output_name).compute(scheduler="threads")
    assert len(target_computed) == 4

    after_computed = after_node.output.compute(scheduler="threads")
    assert len(after_computed) == 4

    callback_nodes = {node_id for _, node_id in callback_events}
    assert callback_nodes == {"before_node", "target_node", "after_node"}

    start_nodes = {node_id for stage, node_id in callback_events if stage == "start"}
    finish_nodes = {node_id for stage, node_id in callback_events if stage == "finish"}
    progress_nodes = {node_id for stage, node_id in callback_events if stage == "progress"}
    assert start_nodes == {"before_node", "target_node", "after_node"}
    assert finish_nodes == {"before_node", "target_node", "after_node"}
    assert progress_nodes == {"before_node", "target_node", "after_node"}

    assert target_events["started"] >= 1
    assert target_events["finished"] >= 1
    assert target_events["progress_calls"] >= 2
    assert target_events["node_ids"] == {"target_node"}

    assert before_events["started"] >= 1
    assert before_events["finished"] >= 1
    assert before_events["progress_calls"] >= 2
    assert before_events["node_ids"] == {"before_node"}

    assert after_events["started"] >= 1
    assert after_events["finished"] >= 1
    assert after_events["progress_calls"] >= 2
    assert after_events["node_ids"] == {"after_node"}
