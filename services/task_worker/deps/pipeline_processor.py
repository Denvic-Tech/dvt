from typing import TYPE_CHECKING, Any

from src.node_dsl import ExecutionSettings
from src.pipeline import PipelineProcessor
from src.pipeline.execution_mode import PipelineExecutionMode
from src.pipeline.types import TaskStopEvent

import config

from .caching import (
    get_data_index_store,
    get_data_store,
    get_metadata_index_store,
    get_metadata_store,
)
from .pipeline_callbacks import (
    on_node_error,
    on_node_metadata,
    on_node_started,
    on_node_success,
    on_task_running,
    on_task_started,
)

if TYPE_CHECKING:
    from src.schemas.internal import TaskInternal


def get_pipeline_processor(
        task: "TaskInternal",
        stop_event: TaskStopEvent | None = None,
        execution_settings: ExecutionSettings | None = None,
) -> PipelineProcessor:
    kwargs: dict[str, Any] = {
        "task": task,
        "stop_event": stop_event,
        "execution_settings": execution_settings,

        "on_task_started": on_task_started,
        "on_task_running": on_task_running,
    }

    if task.send_ws_messages:
        kwargs.update({
            "on_node_metadata": on_node_metadata,
            "on_node_process_start": on_node_started,
            "on_node_process_success": on_node_success,
            "on_node_error": on_node_error,
        })

        if not config.OTHER.DISABLE_STORE:
            kwargs.update({
                "metadata_store": get_metadata_store(),
                "metadata_index_store": get_metadata_index_store(),
            })

    if task.mode == PipelineExecutionMode.FULL and not config.OTHER.DISABLE_STORE:
        kwargs.update({
            "data_store": get_data_store(),
            "data_index_store": get_data_index_store(),
        })

    return PipelineProcessor(**kwargs)
