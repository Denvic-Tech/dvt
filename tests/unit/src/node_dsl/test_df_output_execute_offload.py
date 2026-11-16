"""A DF-output node's synchronous ``process`` must not block the event loop in FULL mode.

The task worker runs its heartbeat sender on the same loop as the pipeline; a blocking
``process`` (read planning with DB round trips) starved it and the Orchestrator reported
``WORKER_LOST`` after the heartbeat timeout.
"""

import asyncio
import threading
import time

import dask.dataframe as dd
import pandas as pd
import pytest

from src.node_dsl import DFOutputBaseNode, OutputField
from src.pipeline.execution_mode import PipelineExecutionMode


class _BlockingProcessNode(DFOutputBaseNode):
    output: dd.DataFrame = OutputField()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.process_thread: threading.Thread | None = None

    def process(self) -> None:
        self.process_thread = threading.current_thread()
        time.sleep(0.6)
        self.output = dd.from_pandas(pd.DataFrame({"value": [1, 2]}), npartitions=1)


@pytest.mark.asyncio
async def test_full_mode_process_runs_off_the_event_loop() -> None:
    node = _BlockingProcessNode(
        user_id="user", project_id="project", task_id="task", node_id="node",
    )
    ticks = 0
    stop = asyncio.Event()

    async def _heartbeat() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.05)

    heartbeat = asyncio.create_task(_heartbeat())
    try:
        await node.execute(PipelineExecutionMode.FULL)
    finally:
        stop.set()
        await heartbeat

    assert node.process_thread is not threading.current_thread()
    # 0.6 s of blocking process at 50 ms ticks: the loop kept running.
    assert ticks >= 5
    assert len(node.output.compute(scheduler="threads")) == 2
