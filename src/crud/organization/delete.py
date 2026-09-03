import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.crud.organization._session import maybe_await
from src.crud.organization.read import get_organizations_by
from src.models import (
    OrganizationRecord,
)
from src.modules.pipeline_graph.infra.db_models import (
    GraphEdgeRecord,
    GraphNodeRecord,
    SubgraphRecord,
)
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.infra.db_models import TaskRecord
from src.modules.user.infra.db_models import UserRecord


async def delete_organization(
    session: AsyncSession,
    organization: OrganizationRecord,
) -> OrganizationRecord:
    await maybe_await(session.delete(organization))
    await maybe_await(session.flush())
    return organization


async def get_organization_dependency_counts(
    session: AsyncSession,
    *,
    organization_id: str,
) -> dict[str, int]:
    # TODO: What with DBConnections?
    models = {
        "users": UserRecord,
        "projects": ProjectRecord,
        "tasks": TaskRecord,
        "graph_nodes": GraphNodeRecord,
        "graph_edges": GraphEdgeRecord,
        "subgraphs": SubgraphRecord,
    }
    counts: dict[str, int] = {}

    for key, model in models.items():
        stmt = sa.select(sa.func.count()).select_from(model).where(model.organization_id == organization_id)
        counts[key] = (await maybe_await(session.execute(stmt))).scalar_one()

    return counts


async def organization_has_dependencies(
    session: AsyncSession,
    *,
    organization_id: str,
) -> bool:
    counts = await get_organization_dependency_counts(session, organization_id=organization_id)
    return any(counts.values())


async def delete_organization_by_id(
    session: AsyncSession,
    *,
    organization_id: str,
) -> OrganizationRecord | None:
    organization = (await get_organizations_by(session, organization_id=organization_id)).first()
    if organization is None:
        return None

    await delete_organization(session, organization)
    return organization

