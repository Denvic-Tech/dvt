from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from src.models.mixins import ModelWithUIID, TimestampedModel

if TYPE_CHECKING:
    from src.models.organization import OrganizationRecord


class GraphEdgeRecord(ModelWithUIID, TimestampedModel, SQLModel, table=True):
    __tablename__ = "graph_edges"

    id: str | None = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    ui_id: str = Field(index=True, nullable=False, description="Edge identifier for UI purposes")

    type: str = Field(nullable=False, description="Edge type")
    source: str = Field(nullable=False, description="Source node ID")

    source_handle: str = Field(nullable=True, description="Handle ID on the source node for this edge")
    target: str = Field(nullable=False, description="Target node ID")
    target_handle: str = Field(nullable=True, description="Handle ID on the target node for this edge")
    subgraph_id: str | None = Field(
        default=None,
        description="UI ID of the subgraph containing this edge",
    )

    project_id: str = Field(
        nullable=False,
        description="ID of the project to which this edge belongs"
    )
    organization_id: str = Field(
        foreign_key="organizations.id",
        nullable=False,
        index=True,
        description="ID of the organization that owns the project",
    )
    organization: "OrganizationRecord" = Relationship()
    user_id: str = Field(nullable=False, description="ID of the user who owns the project")

    __table_args__ = (
        UniqueConstraint('ui_id', 'project_id', name='unique_ui_id_per_project_for_edges'),
        ForeignKeyConstraint(
            ['project_id', 'organization_id'],
            ['projects.id', 'projects.organization_id'],
            name='fk_graph_edges_project_organization'
        ),
    )
