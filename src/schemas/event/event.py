from typing import Annotated, Union

from pydantic import Field

from .log import LogEvent
from .node_execution_status import NodeExecutionStatusEvent
from .task_execution_status import TaskExecutionStatusEvent
from .task_execution_telemetry import TaskExecutionTelemetryEvent
from .node_metadata import NodeMetadataEvent
from .ping import PingEvent
from .progress import ProgressEvent
from .status import StatusUpdateEvent

Event = Annotated[
    Union[
        LogEvent,
        NodeExecutionStatusEvent,
        TaskExecutionStatusEvent,
        TaskExecutionTelemetryEvent,
        NodeMetadataEvent,
        PingEvent,
        ProgressEvent,
        StatusUpdateEvent,
    ],
    Field(discriminator="type"),
]
