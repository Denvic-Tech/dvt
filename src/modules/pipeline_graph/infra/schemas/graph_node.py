from pydantic import BaseModel, Field
from pystructor import partial

from src.node_dsl.core.input_values import NodeInputValues


class Position(BaseModel):
    x: float
    y: float


class GraphNodeData(BaseModel):
    name: str
    displayName: str
    storeEnabled: bool | None = Field(default=False)
    showSignalIo: bool | None = Field(default=False)
    showVariablesIo: bool | None = Field(default=False)
    comment: str | None = None
    inputValues: NodeInputValues = Field(default_factory=dict)


class GraphNodeUISchema(BaseModel):
    id: str
    type: str
    subgraphId: str | None = None
    position: Position
    selected: bool = False
    data: GraphNodeData


@partial(GraphNodeData)
class GraphNodeDataUpdate(BaseModel):
    pass


@partial(GraphNodeUISchema)
class GraphNodeUIUpdateSchema(BaseModel):
    """Schema for updating a graph node in the database."""
    id: str
    data: GraphNodeDataUpdate | None = None
