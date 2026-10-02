"""Execution concepts exposed to extensions."""

from src.node_dsl.cancellation import CancellationToken
from src.node_dsl.exceptions import NodeExecutionCancelled
from src.pipeline.execution_mode import PipelineExecutionMode

ExecutionMode = PipelineExecutionMode
ExecMode = PipelineExecutionMode

__all__ = [
    "CancellationToken",
    "ExecMode",
    "ExecutionMode",
    "NodeExecutionCancelled",
    "PipelineExecutionMode",
]
