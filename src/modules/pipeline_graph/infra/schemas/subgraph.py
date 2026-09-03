from pydantic import BaseModel
from pystructor import partial

from ..schemas.graph_node import Position


class SubgraphData(BaseModel):
    name: str
    displayName: str
    color: str | None = None
    comment: str | None = None


class SubgraphUISchema(BaseModel):
    id: str
    type: str
    position: Position
    selected: bool = False
    expanded: bool = True
    data: SubgraphData


@partial(SubgraphData)
class SubgraphDataUpdate(BaseModel):
    pass


@partial(SubgraphUISchema)
class SubgraphUIUpdateSchema(BaseModel):
    """Schema for updating a subgraph in the database."""
    id: str
    data: SubgraphDataUpdate | None = None
