from pydantic import BaseModel
from pystructor import omit, partial

from src.models.organization import OrganizationRecord


@omit(
    OrganizationRecord,
    "id",
    "created_at",
    "updated_at",
    "users",
    "db_connections",
    "projects",
    "tasks",
    "subgraphs",
)
class OrganizationCreateSchema(BaseModel):
    """Schema for creating an organization."""


@omit(
    OrganizationRecord,
    "users",
    "db_connections",
    "projects",
    "tasks",
    "subgraphs",
)
class OrganizationReadSchema(BaseModel):
    """Schema for reading an organization."""

    projects_count: int = 0

    class Config:
        from_attributes = True


@partial(OrganizationCreateSchema)
class OrganizationUpdateSchema(BaseModel):
    """Schema for updating an organization."""

