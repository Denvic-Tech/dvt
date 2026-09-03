from __future__ import annotations

import asyncio
import gc
import weakref
from types import SimpleNamespace

import dask.dataframe as dd
import pandas as pd
import pytest

from services.task_worker.task_cleanup import (
    TaskExecutionCleanup,
    cleanup_tmp_partd_artifacts,
)


@pytest.mark.asyncio
async def test_repeated_dask_cleanup_releases_processor_graph_references():
    cleanup = TaskExecutionCleanup()
    references = []
    live_task_local_counts: list[int] = []

    for _ in range(6):
        dataframe = dd.from_pandas(pd.DataFrame({"value": range(100)}), npartitions=4)
        # Force a real Dask graph execution before cleanup, closer to a persistent
        # worker processing multiple pipelines rather than only allocating graphs.
        assert int(dataframe.value.sum().compute()) == 4950
        references.append(weakref.ref(dataframe))
        processor = SimpleNamespace(
            nodes_outputs={"node": {"df": dataframe}},
            nodes_output_hashes={"node": {}},
            nodes_metadata={"node": {}},
            node_signal_states={"node": {}},
            executed_nodes=["node"],
            failed_nodes=[],
            skipped_nodes=[],
            restored_nodes=[],
            _completed_node_ids={"node"},
            _recoverable_failed_node_ids=set(),
            _execution_order=["node"],
            _planned_execution_order=["node"],
            _affected_metadata_nodes={"node"},
            pipeline={"node": dataframe},
            task=object(),
            stop_event=object(),
        )

        await cleanup.execute(processor=processor)
        del dataframe
        gc.collect()
        live_task_local_counts.append(sum(ref() is not None for ref in references))

        assert processor.nodes_outputs == {}
        assert processor.pipeline == {}
        assert processor.task is None

    # Task-local Dask collections/resources do not accumulate across sequential
    # executions in one persistent process. A monotonic increase would regress
    # the original reason for per-task child recycling.
    assert live_task_local_counts == [0] * 6
    assert all(reference() is None for reference in references)


@pytest.mark.asyncio
async def test_cleanup_does_not_block_terminalization_on_cancellation_resistant_background_task():
    first_cancel_observed = asyncio.Event()

    async def cancellation_resistant_resource() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            first_cancel_observed.set()
            # Simulate a transport cleanup that does not finish on the first
            # cancellation request.
            await asyncio.Event().wait()

    background_task = asyncio.create_task(
        cancellation_resistant_resource(),
        name="stubborn-transport",
    )
    await asyncio.sleep(0)
    processor = SimpleNamespace(
        nodes_outputs={"node": object()},
        nodes_output_hashes={},
        nodes_metadata={},
        node_signal_states={},
        executed_nodes=[],
        failed_nodes=[],
        skipped_nodes=[],
        restored_nodes=[],
        _completed_node_ids=set(),
        _recoverable_failed_node_ids=set(),
        _execution_order=[],
        _planned_execution_order=[],
        _affected_metadata_nodes=set(),
        pipeline={"node": object()},
        task=object(),
        stop_event=object(),
    )

    cleanup = TaskExecutionCleanup(background_task_cancel_timeout_sec=0.01)
    await cleanup.execute(background_tasks=(background_task,), processor=processor)
    await asyncio.sleep(0)

    assert first_cancel_observed.is_set()
    assert background_task.cancelled()
    assert processor.nodes_outputs == {}
    assert processor.pipeline == {}
    assert processor.task is None


def test_cleanup_tmp_partd_removes_known_artifacts(tmp_path):
    directory = tmp_path / "graph.partd"
    directory.mkdir()
    (directory / "data").write_text("payload", encoding="utf-8")
    file_artifact = tmp_path / "shuffle.partd"
    file_artifact.write_text("payload", encoding="utf-8")

    cleanup_tmp_partd_artifacts(tmp_path)

    assert not directory.exists()
    assert not file_artifact.exists()
