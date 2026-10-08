from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.task_worker.deps import pipeline_processor

from src.node_dsl import ExecutionDateTimePrecision, ExecutionSettings
from src.pipeline.execution_mode import PipelineExecutionMode


class _CapturePipelineProcessor:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_get_pipeline_processor_sets_node_status_callbacks_for_metadata_only(monkeypatch):
    monkeypatch.setattr(pipeline_processor, "PipelineProcessor", _CapturePipelineProcessor)
    monkeypatch.setattr(pipeline_processor.config.OTHER, "DISABLE_STORE", True)
    monkeypatch.setattr(pipeline_processor.config.DATA_CATALOG, "WORKER_OBSERVATION_ENABLED", True)

    task = SimpleNamespace(
        mode=PipelineExecutionMode.METADATA_ONLY,
        send_ws_messages=True,
    )

    processor = pipeline_processor.get_pipeline_processor(task=task)

    assert processor.kwargs["on_node_process_start"] is pipeline_processor.on_node_started
    assert processor.kwargs["on_node_process_success"] is pipeline_processor.on_node_success
    assert processor.kwargs["on_node_error"] is pipeline_processor.on_node_error
    # WS-колбэк идёт первым, каталожное наблюдение вторым.
    assert processor.kwargs["on_node_metadata"].callbacks == (
        pipeline_processor.on_node_metadata,
        pipeline_processor.on_node_metadata_catalog,
    )


def test_catalog_observation_is_wired_without_ws_messages(monkeypatch):
    monkeypatch.setattr(pipeline_processor, "PipelineProcessor", _CapturePipelineProcessor)
    monkeypatch.setattr(pipeline_processor.config.OTHER, "DISABLE_STORE", True)
    monkeypatch.setattr(pipeline_processor.config.DATA_CATALOG, "WORKER_OBSERVATION_ENABLED", True)
    task = SimpleNamespace(mode=PipelineExecutionMode.FULL, send_ws_messages=False)

    processor = pipeline_processor.get_pipeline_processor(task=task)

    assert processor.kwargs["on_node_metadata"] is pipeline_processor.on_node_metadata_catalog
    assert "on_node_process_start" not in processor.kwargs


def test_catalog_observation_can_be_disabled(monkeypatch):
    monkeypatch.setattr(pipeline_processor, "PipelineProcessor", _CapturePipelineProcessor)
    monkeypatch.setattr(pipeline_processor.config.OTHER, "DISABLE_STORE", True)
    monkeypatch.setattr(pipeline_processor.config.DATA_CATALOG, "WORKER_OBSERVATION_ENABLED", False)
    task = SimpleNamespace(mode=PipelineExecutionMode.FULL, send_ws_messages=False)

    processor = pipeline_processor.get_pipeline_processor(task=task)

    assert "on_node_metadata" not in processor.kwargs


@pytest.mark.asyncio
async def test_composed_callbacks_run_in_order_and_accept_extra_kwargs():
    calls: list[str] = []

    async def first(**kwargs):
        calls.append(f"first:{kwargs['node']}")

    async def second(**kwargs):
        calls.append(f"second:{kwargs['extra']}")

    composed = pipeline_processor.compose_node_metadata_callbacks(None, first, second)

    await composed(user_id="u", project_id="p", task_id="t", node="n", metadata={}, extra="x")

    assert calls == ["first:n", "second:x"]


def test_get_pipeline_processor_forwards_execution_settings(monkeypatch):
    monkeypatch.setattr(pipeline_processor, "PipelineProcessor", _CapturePipelineProcessor)
    monkeypatch.setattr(pipeline_processor.config.OTHER, "DISABLE_STORE", True)
    execution_settings = ExecutionSettings(
        datetime_precision=ExecutionDateTimePrecision.SECONDS,
    )
    task = SimpleNamespace(
        mode=PipelineExecutionMode.FULL,
        send_ws_messages=False,
    )

    processor = pipeline_processor.get_pipeline_processor(
        task=task,
        execution_settings=execution_settings,
    )

    assert processor.kwargs["execution_settings"] is execution_settings
