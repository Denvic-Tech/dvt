import dask.dataframe as dd
import pandas as pd
import pytest

import src.node_dsl.base_node.df_output as df_output_module
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.pipeline.execution_mode import PipelineExecutionMode


class _PrewarmTestNode(DFOutputBaseNode):
    df_in: dd.DataFrame = InputField()
    output: dd.DataFrame = OutputField()
    process_calls = 0
    metadata_calls = 0

    def process(self) -> None:
        type(self).process_calls += 1
        self.output = self.df_in

    async def process_metadata(self) -> None:
        type(self).metadata_calls += 1
        self.output = self.df_in.head(0, compute=False)


@pytest.mark.asyncio
async def test_df_output_execute_prewarms_async_worker_in_full_mode(monkeypatch) -> None:
    _PrewarmTestNode.process_calls = 0
    _PrewarmTestNode.metadata_calls = 0
    calls = {"count": 0}

    def _fake_ensure_own_loop():
        calls["count"] += 1
        return None

    monkeypatch.setattr(df_output_module.async_worker, "ensure_own_loop", _fake_ensure_own_loop)

    ddf = dd.from_pandas(pd.DataFrame({"value": [1, 2, 3, 4]}), npartitions=2)
    node = _PrewarmTestNode(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        df_in=ddf,
    )

    await node.execute(PipelineExecutionMode.FULL)

    assert calls["count"] == 1
    assert _PrewarmTestNode.process_calls == 1
    assert _PrewarmTestNode.metadata_calls == 0


@pytest.mark.asyncio
async def test_df_output_execute_does_not_prewarm_in_metadata_mode(monkeypatch) -> None:
    _PrewarmTestNode.process_calls = 0
    _PrewarmTestNode.metadata_calls = 0
    calls = {"count": 0}

    def _fake_ensure_own_loop():
        calls["count"] += 1
        return None

    monkeypatch.setattr(df_output_module.async_worker, "ensure_own_loop", _fake_ensure_own_loop)

    ddf = dd.from_pandas(pd.DataFrame({"value": [1, 2]}), npartitions=1)
    node = _PrewarmTestNode(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        df_in=ddf,
    )

    await node.execute(PipelineExecutionMode.METADATA_ONLY)

    assert calls["count"] == 0
    assert _PrewarmTestNode.process_calls == 0
    assert _PrewarmTestNode.metadata_calls == 1
