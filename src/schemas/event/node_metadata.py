from typing import Literal

from pydantic import Field

from .base import EventBase
from .types import EventType

from ...node_dsl.types import NodeMetadata


class NodeMetadataEvent(EventBase):
    type: Literal[EventType.NODE_METADATA] = EventType.NODE_METADATA

    project_id: str = Field(description="ID проекта")
    task_id: str = Field(description="ID задачи")
    node_id: str = Field(description="ID узла")
    metadata: NodeMetadata = Field(description="Метаданные узла ({output_name: MetaData})")
