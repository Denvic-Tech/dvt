from uuid import uuid4

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlmodel import Field, SQLModel

from src.models.mixins import ModelWithUIID, TimestampedModel


class SubgraphRecord(ModelWithUIID, TimestampedModel, SQLModel, table=True):
    __tablename__ = "subgraphs"

    id: str | None = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    ui_id: str = Field(index=True, nullable=False, description="Subgraph identifier for UI purposes")
    type: str = Field(nullable=False, description="Subgraph type")

    position_x: float = Field(description="X position of the subgraph in the graph")
    position_y: float = Field(description="Y position of the subgraph in the graph")
    selected: bool = Field(default=False, description="Is subgraph selected in the UI")
    expanded: bool = Field(default=True, description="Is subgraph expanded in the UI")

    name: str = Field(nullable=False, description="Subgraph name")
    display_name: str = Field(nullable=False, description="Subgraph display name for UI")
    color: str | None = Field(
        default=None,
        description="Hex color code for the subgraph in the UI",
        nullable=True,
    )
    comment: str | None = Field(
        default=None,
        description="User note visible in the UI for this subgraph",
        max_length=20480,
    )

    project_id: str = Field(
        nullable=False,
        description="ID of the project to which this subgraph belongs",
    )
    organization_id: str = Field(
        foreign_key="organizations.id",
        nullable=False,
        index=True,
        description="ID of the organization that owns the project",
    )
    user_id: str = Field(nullable=False, description="ID of the user who owns the project")

    __table_args__ = (
        UniqueConstraint("ui_id", "project_id", name="unique_ui_id_per_project_for_subgraphs"),
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_subgraphs_project_organization",
        ),
    )
