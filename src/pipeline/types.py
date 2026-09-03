from typing import Protocol, runtime_checkable, Dict
from typing import TYPE_CHECKING

from src.node_dsl.types import NodeMetadata

if TYPE_CHECKING:
    from sqlmodel import Session

    from src.types import MaybeAwaitable
    from src.schemas.internal import TaskInternal
    from src.schemas.internal import NodeData


Pipeline = Dict[str, "NodeData"]  # {node_id: NodeData}
PipelineMetadata = Dict[str, NodeMetadata]  # {node_id: NodeMetadata}


@runtime_checkable
class TaskStopEvent(Protocol):
    def is_set(self) -> bool:
        ...

    def set(self) -> None:
        ...


class TaskCallback(Protocol):
    def __call__(self, task: "TaskInternal", session: "Session | None" = None) -> "MaybeAwaitable[None]":
        ...


OnTaskStartedCallback = TaskCallback
OnTaskRunningCallback = TaskCallback
OnTaskSuccessCallback = TaskCallback
OnTaskCancelledCallback = TaskCallback


class OnTaskErrorCallback(Protocol):
    def __call__(self,
                 task: "TaskInternal",
                 message: str,
                 session: "Session | None" = None) -> "MaybeAwaitable[None]":
        ...
