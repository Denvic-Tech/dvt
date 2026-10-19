import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter

from services.gateway.deps.project import UserProjectByPath

from src.crud import project as project_crud
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.logger import logger
from src.modules.data_catalog.facade import rebuild_project_catalog_projection
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.project_transfer.domain.policies import remap_graph_snapshot
from src.modules.project_transfer.infra.graph_cloner import (
    copy_service_file_objects,
    insert_graph_snapshot,
    read_graph_snapshot,
)
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.schemas.http.project import ProjectReadSchema, ProjectUpdateSchema

router = APIRouter()


def bump_name(name: str) -> str:
    m = re.search(r"(.*)\s(\d+)$", name)
    if m:
        base = m.group(1)
        num = int(m.group(2)) + 1
        return f"{base} {num}"
    return f"{name} 2"


@router.post("/{project_id}/copy", response_model=ProjectReadSchema)
async def copy_project(
    project_id: str,
    data: ProjectUpdateSchema,
    session: AsyncSessionDepends,
    user: UserAccessOnly,  # noqa: ARG001 - enforces authenticated access
    project: UserProjectByPath,
) -> ProjectReadSchema:
    payload = data.model_dump(exclude_unset=True)
    new_project_name = payload.get("name", bump_name(project.name))

    now = datetime.now(tz=UTC)
    new_project = ProjectRecord(
        id=str(uuid.uuid4()),
        name=new_project_name,
        user_id=project.user_id,
        organization_id=project.organization_id,
        is_deleted=False,
        created_at=now,
        updated_at=now,
    )

    session.add(new_project)
    await session.flush()

    source_snapshot = await read_graph_snapshot(session, project_id)
    remapped = remap_graph_snapshot(
        source_snapshot,
        organization_id=new_project.organization_id,
        project_id=new_project.id,
    )
    await insert_graph_snapshot(
        session,
        remapped.snapshot,
        project_id=new_project.id,
        user_id=new_project.user_id,
        organization_id=new_project.organization_id,
        now=now,
    )
    await copy_service_file_objects(
        session,
        organization_id=new_project.organization_id,
        source_project_id=project_id,
        target_project_id=new_project.id,
        rewrites=remapped.service_files_rewrites,
        now=now,
    )

    await session.commit()

    try:
        await rebuild_project_catalog_projection(
            session=session,
            project_id=new_project.id,
            organization_id=new_project.organization_id,
            force=True,
        )
        await session.commit()
    except Exception:
        logger.exception("Data catalog projection build failed for copied project {}", new_project.id)
        await session.rollback()

    await session.refresh(new_project)
    user_emails = await project_crud.get_user_emails_by_ids(
        session,
        user_ids=[project.user_id],
    )

    return ProjectReadSchema(
        **new_project.model_dump(),
        user_email=user_emails.get(project.user_id),
    )
