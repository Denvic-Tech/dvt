from dataclasses import dataclass
from typing import Protocol, TypeVar, Generic, Annotated, Dict, Literal
from typing import TYPE_CHECKING

from pydantic import Field

from core.types import Metadata
from src.node_dsl.variables.types import VariableMapMetadata

from src.types.common import MaybeAwaitable

if TYPE_CHECKING:
    from src.node_dsl import BaseNode


NodeOutputMetadata = Annotated[Metadata | VariableMapMetadata, Field(discriminator="type")]
NodeMetadata = Dict[str | Literal["output_variables"], NodeOutputMetadata | None]  # {output_name: Metadata}


class OnNodeProgressStepCallback(Protocol):
    def __call__(self,
                 user_id: str,
                 project_id: str,
                 task_id: str,
                 node: "BaseNode",
                 current_step: int,
                 total_steps: int) -> None:
        ...


class NodeCallback(Protocol):
    def __call__(self,
                 user_id: str,
                 project_id: str,
                 task_id: str,
                 node: "BaseNode") -> MaybeAwaitable[None]:
        ...


OnNodeProcessStartCallback = NodeCallback
OnNodeProcessSuccessCallback = NodeCallback


class OnNodeErrorCallback(Protocol):
    def __call__(self,
                 user_id: str,
                 project_id: str,
                 task_id: str,
                 node: "BaseNode",
                 message: str) -> MaybeAwaitable[None]:
        ...


class OnNodeMetadataCallback(Protocol):
    def __call__(
            self,
            user_id: str,
            project_id: str,
            task_id: str,
            node: "BaseNode",
            metadata: NodeMetadata) -> MaybeAwaitable[None]:
        ...


T_co = TypeVar("T_co", covariant=True)


@dataclass(frozen=True, slots=True)
class NodeOutput(Generic[T_co]):
    value: T_co

    def __repr__(self) -> str:
        return f"NodeOutput(value={type(self.value)})"
