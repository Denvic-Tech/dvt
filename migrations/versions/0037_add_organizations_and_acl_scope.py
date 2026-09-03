"""Add organizations and organization scoped ACL fields.

Revision ID: 0037
Revises: 0036
Create Date: 2026-03-18 14:00:00.000000
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


revision: str = "0037"
down_revision: Union[str, Sequence[str], None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def upgrade() -> None:
    bind = op.get_bind()
    default_org_id = str(uuid4())
    now = _utcnow()

    op.create_table(
        "organizations",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("inn", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_organizations_name"), "organizations", ["name"], unique=False)
    op.create_index(op.f("ix_organizations_inn"), "organizations", ["inn"], unique=True)

    organizations_table = sa.table(
        "organizations",
        sa.column("id", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("inn", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    bind.execute(
        sa.insert(organizations_table).values(
            id=default_org_id,
            name="Default organization",
            description=None,
            inn=None,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )

    for table_name in ("users", "db_connections", "projects", "tasks", "graph_nodes", "graph_edges", "subgraphs"):
        op.add_column(table_name, sa.Column("organization_id", sa.String(), nullable=True))

    bind.execute(sa.text("UPDATE users SET organization_id = :org_id"), {"org_id": default_org_id})
    bind.execute(sa.text("UPDATE db_connections SET organization_id = :org_id"), {"org_id": default_org_id})
    bind.execute(sa.text("UPDATE projects SET organization_id = :org_id"), {"org_id": default_org_id})
    bind.execute(sa.text("UPDATE tasks SET organization_id = :org_id"), {"org_id": default_org_id})
    bind.execute(sa.text("UPDATE graph_nodes SET organization_id = :org_id"), {"org_id": default_org_id})
    bind.execute(sa.text("UPDATE graph_edges SET organization_id = :org_id"), {"org_id": default_org_id})
    bind.execute(sa.text("UPDATE subgraphs SET organization_id = :org_id"), {"org_id": default_org_id})

    op.alter_column("users", "organization_id", existing_type=sa.String(), nullable=False)
    op.alter_column("db_connections", "organization_id", existing_type=sa.String(), nullable=False)
    op.alter_column("projects", "organization_id", existing_type=sa.String(), nullable=False)
    op.alter_column("tasks", "organization_id", existing_type=sa.String(), nullable=False)
    op.alter_column("graph_nodes", "organization_id", existing_type=sa.String(), nullable=False)
    op.alter_column("graph_edges", "organization_id", existing_type=sa.String(), nullable=False)
    op.alter_column("subgraphs", "organization_id", existing_type=sa.String(), nullable=False)

    op.create_index(op.f("ix_users_organization_id"), "users", ["organization_id"], unique=False)
    op.create_index(op.f("ix_db_connections_organization_id"), "db_connections", ["organization_id"], unique=False)
    op.create_index(op.f("ix_projects_organization_id"), "projects", ["organization_id"], unique=False)
    op.create_index(op.f("ix_tasks_organization_id"), "tasks", ["organization_id"], unique=False)
    op.create_index(op.f("ix_graph_nodes_organization_id"), "graph_nodes", ["organization_id"], unique=False)
    op.create_index(op.f("ix_graph_edges_organization_id"), "graph_edges", ["organization_id"], unique=False)
    op.create_index(op.f("ix_subgraphs_organization_id"), "subgraphs", ["organization_id"], unique=False)

    op.create_foreign_key("fk_users_organization", "users", "organizations", ["organization_id"], ["id"])
    op.create_foreign_key("fk_db_connections_organization", "db_connections", "organizations", ["organization_id"], ["id"])
    op.create_foreign_key("fk_projects_organization", "projects", "organizations", ["organization_id"], ["id"])
    op.create_foreign_key("fk_tasks_organization", "tasks", "organizations", ["organization_id"], ["id"])
    op.create_foreign_key("fk_graph_nodes_organization", "graph_nodes", "organizations", ["organization_id"], ["id"])
    op.create_foreign_key("fk_graph_edges_organization", "graph_edges", "organizations", ["organization_id"], ["id"])
    op.create_foreign_key("fk_subgraphs_organization", "subgraphs", "organizations", ["organization_id"], ["id"])

    op.drop_constraint("fk_graph_nodes_project_user", "graph_nodes", type_="foreignkey")
    op.drop_constraint("fk_graph_edges_project_user", "graph_edges", type_="foreignkey")
    op.drop_constraint("fk_subgraphs_project_user", "subgraphs", type_="foreignkey")

    op.drop_constraint("unique_project_id_user_id", "projects", type_="unique")
    op.create_unique_constraint("unique_project_id_organization_id", "projects", ["id", "organization_id"])

    op.create_foreign_key(
        "fk_graph_nodes_project_organization",
        "graph_nodes",
        "projects",
        ["project_id", "organization_id"],
        ["id", "organization_id"],
    )
    op.create_foreign_key(
        "fk_graph_edges_project_organization",
        "graph_edges",
        "projects",
        ["project_id", "organization_id"],
        ["id", "organization_id"],
    )
    op.create_foreign_key(
        "fk_subgraphs_project_organization",
        "subgraphs",
        "projects",
        ["project_id", "organization_id"],
        ["id", "organization_id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_subgraphs_project_organization", "subgraphs", type_="foreignkey")
    op.drop_constraint("fk_graph_edges_project_organization", "graph_edges", type_="foreignkey")
    op.drop_constraint("fk_graph_nodes_project_organization", "graph_nodes", type_="foreignkey")

    op.drop_constraint("unique_project_id_organization_id", "projects", type_="unique")
    op.create_unique_constraint("unique_project_id_user_id", "projects", ["id", "user_id"])

    op.create_foreign_key(
        "fk_subgraphs_project_user",
        "subgraphs",
        "projects",
        ["project_id", "user_id"],
        ["id", "user_id"],
    )
    op.create_foreign_key(
        "fk_graph_edges_project_user",
        "graph_edges",
        "projects",
        ["project_id", "user_id"],
        ["id", "user_id"],
    )
    op.create_foreign_key(
        "fk_graph_nodes_project_user",
        "graph_nodes",
        "projects",
        ["project_id", "user_id"],
        ["id", "user_id"],
    )

    op.drop_constraint("fk_subgraphs_organization", "subgraphs", type_="foreignkey")
    op.drop_constraint("fk_graph_edges_organization", "graph_edges", type_="foreignkey")
    op.drop_constraint("fk_graph_nodes_organization", "graph_nodes", type_="foreignkey")
    op.drop_constraint("fk_tasks_organization", "tasks", type_="foreignkey")
    op.drop_constraint("fk_projects_organization", "projects", type_="foreignkey")
    op.drop_constraint("fk_db_connections_organization", "db_connections", type_="foreignkey")
    op.drop_constraint("fk_users_organization", "users", type_="foreignkey")

    op.drop_index(op.f("ix_subgraphs_organization_id"), table_name="subgraphs")
    op.drop_index(op.f("ix_graph_edges_organization_id"), table_name="graph_edges")
    op.drop_index(op.f("ix_graph_nodes_organization_id"), table_name="graph_nodes")
    op.drop_index(op.f("ix_tasks_organization_id"), table_name="tasks")
    op.drop_index(op.f("ix_projects_organization_id"), table_name="projects")
    op.drop_index(op.f("ix_db_connections_organization_id"), table_name="db_connections")
    op.drop_index(op.f("ix_users_organization_id"), table_name="users")

    op.drop_column("subgraphs", "organization_id")
    op.drop_column("graph_edges", "organization_id")
    op.drop_column("graph_nodes", "organization_id")
    op.drop_column("tasks", "organization_id")
    op.drop_column("projects", "organization_id")
    op.drop_column("db_connections", "organization_id")
    op.drop_column("users", "organization_id")

    op.drop_index(op.f("ix_organizations_inn"), table_name="organizations")
    op.drop_index(op.f("ix_organizations_name"), table_name="organizations")
    op.drop_table("organizations")
