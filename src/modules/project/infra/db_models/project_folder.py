from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from src.models.mixins import TimestampedModel


class ProjectFolderRecord(TimestampedModel, SQLModel, table=True):
    __tablename__ = "project_folders"

    id: str | None = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str = Field(nullable=False, index=True, description="Project folder name")
    parent_id: str | None = Field(
        default=None,
        nullable=True,
        index=True,
        description="Parent project folder ID",
    )
    user_id: str = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
        description="ID пользователя, которому принадлежит папка проектов",
    )
    organization_id: str = Field(
        foreign_key="organizations.id",
        nullable=False,
        index=True,
        description="ID организации, которой принадлежит папка проектов",
    )
    is_deleted: bool = Field(default=False, nullable=False, description="Flag indicating if folder is deleted")

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="unique_project_folder_id_organization_id"),
        ForeignKeyConstraint(
            ["parent_id", "organization_id"],
            ["project_folders.id", "project_folders.organization_id"],
            name="fk_project_folders_parent_organization",
        ),
        CheckConstraint("id != parent_id", name="check_project_folders_not_self_parent"),
        Index(
            "ix_project_folders_org_parent_deleted",
            "organization_id",
            "parent_id",
            "is_deleted",
        ),
        Index(
            "ix_project_folders_org_user_parent_deleted",
            "organization_id",
            "user_id",
            "parent_id",
            "is_deleted",
        ),
    )
