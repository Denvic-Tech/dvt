from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlmodel import Column, Field, Relationship, SQLModel

from src.models.mixins import ModelWithUIID, TimestampedModel
from src.models.sa_types import JSONBCompat
from src.node_dsl.core.input_values import NodeInputValues

if TYPE_CHECKING:
    from src.models.organization import OrganizationRecord


class GraphNodeRecord(ModelWithUIID, TimestampedModel, SQLModel, table=True):

    __tablename__ = "graph_nodes"

    id: str | None = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    ui_id: str = Field(index=True, nullable=False, description="Node identifier for UI purposes")
    type: str = Field(nullable=False, description="Node type")

    position_x: float = Field(description="X position of the node in the graph")
    position_y: float = Field(description="Y position of the node in the graph")
    selected: bool = Field(default=False, description="Is node selected in the UI")

    name: str = Field(nullable=False, description="Node name")
    display_name: str = Field(nullable=False, description="Node display name for UI")
    comment: str | None = Field(
        default=None,
        description="User note visible in the UI for this node",
        max_length=20480
    )
    input_values: "NodeInputValues | None" = Field(
        default_factory=dict,
        sa_column=Column(JSONBCompat, nullable=True),
    )
    store_enabled: bool | None = Field(
        default=False,
        description="Flag indicating if storage is enabled for this node",
    )
    show_signal_io: bool = Field(
        default=False,
        nullable=False,
        description="Flag indicating if signal inputs/outputs are shown for this node in the UI",
    )
    show_variables_io: bool = Field(
        default=False,
        nullable=False,
        description="Flag indicating if variables inputs/outputs are shown for this node in the UI",
    )
    subgraph_id: str | None = Field(
        default=None,
        description="UI ID of the subgraph containing this node",
    )

    project_id: str = Field(
        nullable=False,
        description="ID of the project to which this node belongs"
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
        UniqueConstraint('ui_id', 'project_id', name='unique_ui_id_per_project_for_nodes'),
        ForeignKeyConstraint(
            ['project_id', 'organization_id'],
            ['projects.id', 'projects.organization_id'],
            name='fk_graph_nodes_project_organization'
        ),
    )
