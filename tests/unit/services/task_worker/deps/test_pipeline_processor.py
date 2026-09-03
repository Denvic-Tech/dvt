from __future__ import annotations

from types import SimpleNamespace

from services.task_worker.deps import pipeline_processor

from src.node_dsl import ExecutionDateTimePrecision, ExecutionSettings
from src.pipeline.execution_mode import PipelineExecutionMode


class _CapturePipelineProcessor:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_get_pipeline_processor_sets_node_status_callbacks_for_metadata_only(monkeypatch):
    monkeypatch.setattr(pipeline_processor, "PipelineProcessor", _CapturePipelineProcessor)
    monkeypatch.setattr(pipeline_processor.config.OTHER, "DISABLE_STORE", True)

    task = SimpleNamespace(
        mode=PipelineExecutionMode.METADATA_ONLY,
        send_ws_messages=True,
    )

    processor = pipeline_processor.get_pipeline_processor(task=task)

    assert processor.kwargs["on_node_process_start"] is pipeline_processor.on_node_started
    assert processor.kwargs["on_node_process_success"] is pipeline_processor.on_node_success
    assert processor.kwargs["on_node_error"] is pipeline_processor.on_node_error
    assert processor.kwargs["on_node_metadata"] is pipeline_processor.on_node_metadata


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
