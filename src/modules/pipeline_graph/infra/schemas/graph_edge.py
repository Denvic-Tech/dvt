from pydantic import BaseModel, Field
from pystructor import partial


class GraphEdgeUISchema(BaseModel):
    id: str
    type: str
    subgraphId: str | None = None
    source: str
    sourceHandle: str = Field(
        None, description="Handle ID on the source edge for this edge"
    )
    target: str
    targetHandle: str = Field(
        None, description="Handle ID on the target edge for this edge"
    )


@partial(GraphEdgeUISchema)
class GraphEdgeUpdateUISchema(BaseModel):
    """Schema for updating a graph edge in the UI."""
