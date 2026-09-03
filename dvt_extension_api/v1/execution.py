"""Execution concepts exposed to extensions."""

from src.pipeline.execution_mode import PipelineExecutionMode

ExecutionMode = PipelineExecutionMode
ExecMode = PipelineExecutionMode

__all__ = ["ExecMode", "ExecutionMode", "PipelineExecutionMode"]
