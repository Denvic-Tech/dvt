import uuid
from datetime import UTC, datetime
from typing import Literal

import sqlalchemy as sa
from fastapi import HTTPException, status

from src import exceptions as exc
from src.crud import project as project_crud
from src.db import AsyncSession
from src.modules.project.infra.db_models import ProjectFolderRecord, ProjectRecord
from src.modules.task_execution.infra.queries import get_recent_project_runs_by_project_ids
from src.modules.user.infra.db_models import UserRecord
from src.schemas.http.common import CommonResponse
from src.schemas.http.project import (
    ProjectCreateSchema,
    ProjectFolderCreateSchema,
    ProjectFolderItemSchema,
    ProjectFolderReadSchema,
    ProjectFolderUpdateSchema,
    ProjectItemsPageSchema,
    ProjectLastRunSchema,
    ProjectReadSchema,
    ProjectsDeleteSchema,
    ProjectSearchPageSchema,
    ProjectUpdateSchema,
)
from src.utils.access_control import (
    AccessScope,
    build_owner_or_org_filters,
    can_manage_organization,
    get_access_scope,
)
from src.utils.project_variables import normalize_project_variables_storage_map
from src.utils.user_roles import user_has_admin_access, user_has_global_access

from .common import build_has_more

PROJECT_LAST_RUNS_LIMIT = 5
PROJECT_FOLDER_MAX_DEPTH = 5
ProjectSearchItemType = Literal["all", "folder", "project"]


async def _get_accessible_project_ids_for_deletion(
        *,
        session: AsyncSession,
        user: UserRecord,
        project_ids: list[str],
) -> list[str]:
    return (
        await session.execute(
            sa.select(ProjectRecord.id).where(
                ProjectRecord.id.in_(project_ids),
                *build_owner_or_org_filters(
                    user=user,
                    organization_column=ProjectRecord.organization_id,
                    owner_column=ProjectRecord.user_id,
                ),
                ProjectRecord.is_deleted == False,
            )
        )
    ).scalars().all()


def _normalize_folder_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Folder name must not be empty",
        )
    return normalized


async def _get_accessible_folder(
        *,
        session: AsyncSession,
        user: UserRecord,
        folder_id: str,
        access_scope: AccessScope | None = None,
) -> ProjectFolderRecord:
    resolved_access_scope = access_scope or get_access_scope(user)
    folder = await project_crud.get_folder_by_id(
        session,
        folder_id=folder_id,
        organization_id=resolved_access_scope.organization_id,
        owner_user_id=resolved_access_scope.owner_user_id,
    )
    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Project folder with ID "{folder_id}" not found',
        )
    return folder


def _get_effective_access_scope(
        *,
        user: UserRecord,
        organization_id: str | None = None,
) -> AccessScope:
    access_scope = get_access_scope(user)
    if organization_id is None:
        return access_scope

    if not can_manage_organization(user, organization_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f'Access to organization "{organization_id}" is forbidden',
        )

    return AccessScope(
        organization_id=organization_id,
        owner_user_id=access_scope.owner_user_id,
    )


def _can_use_parent_folder_for_target(
        *,
        user: UserRecord,
        parent: ProjectFolderRecord,
        owner_user_id: str,
        organization_id: str,
        allow_cross_organization: bool,
) -> bool:
    if user_has_global_access(user):
        return allow_cross_organization or parent.organization_id == organization_id

    if user_has_admin_access(user):
        return (
            can_manage_organization(user, organization_id)
            and parent.organization_id == organization_id
        )

    return parent.organization_id == organization_id and parent.user_id == owner_user_id


async def _validate_parent_folder(
        *,
        session: AsyncSession,
        user: UserRecord,
        parent_id: str | None,
        owner_user_id: str,
        organization_id: str,
        subtree_depth: int = 1,
        allow_cross_organization: bool = False,
) -> ProjectFolderRecord | None:
    if parent_id is None:
        if subtree_depth > PROJECT_FOLDER_MAX_DEPTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Project folder depth cannot exceed {PROJECT_FOLDER_MAX_DEPTH}",
            )
        return None

    parent = await _get_accessible_folder(
        session=session,
        user=user,
        folder_id=parent_id,
    )
    if not _can_use_parent_folder_for_target(
        user=user,
        parent=parent,
        owner_user_id=owner_user_id,
        organization_id=organization_id,
        allow_cross_organization=allow_cross_organization,
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Project folder with ID "{parent_id}" not found',
        )

    parent_depth = await project_crud.get_folder_depth(
        session,
        folder_id=parent.id,
        organization_id=parent.organization_id,
        max_depth=PROJECT_FOLDER_MAX_DEPTH,
    )
    if parent_depth is None or parent_depth + subtree_depth > PROJECT_FOLDER_MAX_DEPTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Project folder depth cannot exceed {PROJECT_FOLDER_MAX_DEPTH}",
        )
    return parent


async def _validate_project_folder_target(
        *,
        session: AsyncSession,
        user: UserRecord,
        folder_id: str | None,
        project_owner_user_id: str,
        organization_id: str,
) -> None:
    await _validate_parent_folder(
        session=session,
        user=user,
        parent_id=folder_id,
        owner_user_id=project_owner_user_id,
        organization_id=organization_id,
        allow_cross_organization=True,
    )


def _project_last_runs_from_tasks(tasks) -> list[ProjectLastRunSchema]:
    return [
        ProjectLastRunSchema.model_validate(
            {
                "task_id": task.task_id,
                "status": task.status,
                "queued_at": task.queued_at,
                "started_at": task.started_at,
                "finished_at": task.finished_at,
                "message": task.message,
                "termination_reason": task.termination_reason,
                "schedule_run_id": task.schedule_run_id,
                "attempt_number": task.schedule_attempt,
                "is_retry": (task.schedule_attempt or 1) > 1,
            },
        )
        for task in tasks
    ]


def _folder_to_read_schema(
        folder: ProjectFolderRecord,
        *,
        user_email: str | None = None,
) -> ProjectFolderReadSchema:
    return ProjectFolderReadSchema(
        **folder.model_dump(),
        user_email=user_email,
    )


def _project_to_read_schema(
        project: ProjectRecord,
        *,
        user_email: str | None = None,
        last_runs_by_project_id: dict[str, list] | None = None,
) -> ProjectReadSchema:
    last_runs = []
    if last_runs_by_project_id is not None:
        last_runs = _project_last_runs_from_tasks(
            last_runs_by_project_id.get(project.id, [])
        )

    return ProjectReadSchema(
        **project.model_dump(),
        user_email=user_email,
        last_runs=last_runs,
    )


async def _get_last_runs_by_project_id(
        *,
        session: AsyncSession,
        user: UserRecord,
        project_ids: list[str],
        access_scope: AccessScope | None = None,
) -> dict[str, list]:
    if not project_ids:
        return {}
    resolved_access_scope = access_scope or get_access_scope(user)
    return await get_recent_project_runs_by_project_ids(
        session,
        project_ids=project_ids,
        organization_id=resolved_access_scope.organization_id,
        owner_user_id=resolved_access_scope.owner_user_id,
        per_project_limit=PROJECT_LAST_RUNS_LIMIT,
    )


async def _build_project_folder_items(
        *,
        session: AsyncSession,
        user: UserRecord,
        item_refs,
        include_last_runs: bool,
        access_scope: AccessScope | None = None,
) -> list[ProjectFolderItemSchema]:
    resolved_access_scope = access_scope or get_access_scope(user)
    folder_ids = [item.item_id for item in item_refs if item.item_type == "folder"]
    project_ids = [item.item_id for item in item_refs if item.item_type == "project"]
    folders = {
        folder.id: folder
        for folder in await project_crud.get_folders_by_ids(
            session,
            folder_ids=folder_ids,
            organization_id=resolved_access_scope.organization_id,
            owner_user_id=resolved_access_scope.owner_user_id,
        )
    }
    projects = {
        project.id: project
        for project in await project_crud.get_projects_by_ids(
            session,
            project_ids=project_ids,
            organization_id=resolved_access_scope.organization_id,
            owner_user_id=resolved_access_scope.owner_user_id,
        )
    }
    user_emails = await project_crud.get_user_emails_by_ids(
        session,
        user_ids=[
            *(folder.user_id for folder in folders.values()),
            *(project.user_id for project in projects.values()),
        ],
    )
    last_runs_by_project_id = (
        await _get_last_runs_by_project_id(
            session=session,
            user=user,
            project_ids=project_ids,
            access_scope=resolved_access_scope,
        )
        if include_last_runs
        else {}
    )

    items: list[ProjectFolderItemSchema] = []
    for item_ref in item_refs:
        if item_ref.item_type == "folder" and item_ref.item_id in folders:
            items.append(
                ProjectFolderItemSchema(
                    type="folder",
                    folder=_folder_to_read_schema(
                        folders[item_ref.item_id],
                        user_email=user_emails.get(folders[item_ref.item_id].user_id),
                    ),
                )
            )
        elif item_ref.item_type == "project" and item_ref.item_id in projects:
            items.append(
                ProjectFolderItemSchema(
                    type="project",
                    project=_project_to_read_schema(
                        projects[item_ref.item_id],
                        user_email=user_emails.get(projects[item_ref.item_id].user_id),
                        last_runs_by_project_id=last_runs_by_project_id,
                    ),
                )
            )
    return items


async def get_project_items_route_impl(
        *,
        folder_id: str | None,
        organization_id: str | None,
        limit: int,
        offset: int,
        sort_by: Literal["default", "updated_at"],
        sort_order: Literal["asc", "desc"],
        include_last_runs: bool,
        session: AsyncSession,
        user: UserRecord,
) -> ProjectItemsPageSchema:
    access_scope = _get_effective_access_scope(
        user=user,
        organization_id=organization_id,
    )
    if folder_id is not None:
        await _get_accessible_folder(
            session=session,
            user=user,
            folder_id=folder_id,
            access_scope=access_scope,
        )

    page = await project_crud.get_project_folder_items_page(
        session,
        parent_id=folder_id,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    items = await _build_project_folder_items(
        session=session,
        user=user,
        item_refs=page.items,
        include_last_runs=include_last_runs,
        access_scope=access_scope,
    )
    return ProjectItemsPageSchema(
        items=items,
        total=page.total,
        limit=limit,
        offset=offset,
        has_more=build_has_more(offset=offset, page_size=len(items), total=page.total),
        folder_id=folder_id,
    )


async def create_project_folder_route_impl(
        *,
        data: ProjectFolderCreateSchema,
        session: AsyncSession,
        user: UserRecord,
) -> ProjectFolderReadSchema:
    name = _normalize_folder_name(data.name)
    await _validate_parent_folder(
        session=session,
        user=user,
        parent_id=data.parent_id,
        owner_user_id=user.id,
        organization_id=user.organization_id,
    )

    date_now = datetime.now(tz=UTC)
    folder = ProjectFolderRecord(
        id=str(uuid.uuid4()),
        name=name,
        parent_id=data.parent_id,
        user_id=user.id,
        organization_id=user.organization_id,
        created_at=date_now,
        updated_at=date_now,
    )
    session.add(folder)
    await session.commit()
    await session.refresh(folder)
    return _folder_to_read_schema(folder, user_email=user.email)


async def update_project_folder_route_impl(
        *,
        folder_id: str,
        data: ProjectFolderUpdateSchema,
        session: AsyncSession,
        user: UserRecord,
) -> ProjectFolderReadSchema:
    folder = await _get_accessible_folder(session=session, user=user, folder_id=folder_id)
    update_payload = data.model_dump(exclude_unset=True)

    if "name" in update_payload and update_payload["name"] is not None:
        folder.name = _normalize_folder_name(update_payload["name"])

    if "parent_id" in update_payload:
        new_parent_id = update_payload["parent_id"]
        if new_parent_id == folder.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Project folder cannot be moved into itself",
            )

        descendants = await project_crud.get_descendant_folder_ids(
            session,
            folder_id=folder.id,
            organization_id=folder.organization_id,
            max_depth=PROJECT_FOLDER_MAX_DEPTH,
        )
        if new_parent_id in descendants:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Project folder cannot be moved into its descendant",
            )

        subtree_depth = await project_crud.get_folder_subtree_depth(
            session,
            folder_id=folder.id,
            organization_id=folder.organization_id,
            max_depth=PROJECT_FOLDER_MAX_DEPTH,
        )
        await _validate_parent_folder(
            session=session,
            user=user,
            parent_id=new_parent_id,
            owner_user_id=folder.user_id,
            organization_id=folder.organization_id,
            subtree_depth=subtree_depth,
        )
        folder.parent_id = new_parent_id

    folder.updated_at = datetime.now(tz=UTC)
    session.add(folder)
    await session.commit()
    await session.refresh(folder)
    folder_user_emails = await project_crud.get_user_emails_by_ids(
        session,
        user_ids=[folder.user_id],
    )
    return _folder_to_read_schema(
        folder,
        user_email=folder_user_emails.get(folder.user_id),
    )


async def delete_project_folder_route_impl(
        *,
        folder_id: str,
        session: AsyncSession,
        user: UserRecord,
) -> CommonResponse:
    folder = await _get_accessible_folder(session=session, user=user, folder_id=folder_id)
    if await project_crud.folder_has_children(session, folder_id=folder.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project folder must be empty before deletion",
        )

    folder.is_deleted = True
    folder.updated_at = datetime.now(tz=UTC)
    session.add(folder)
    await session.commit()
    return CommonResponse(success=True, message="Project folder successfully deleted.")


async def search_projects_route_impl(
        *,
        name: str,
        item_type: ProjectSearchItemType,
        folder_id: str | None,
        organization_id: str | None,
        limit: int,
        offset: int,
        sort_by: Literal["default", "updated_at"],
        sort_order: Literal["asc", "desc"],
        include_last_runs: bool,
        session: AsyncSession,
        user: UserRecord,
) -> ProjectSearchPageSchema:
    normalized_name = name.strip()
    if not normalized_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Search name must not be empty",
        )

    access_scope = _get_effective_access_scope(
        user=user,
        organization_id=organization_id,
    )
    if folder_id is not None:
        await _get_accessible_folder(
            session=session,
            user=user,
            folder_id=folder_id,
            access_scope=access_scope,
        )

    page = await project_crud.search_project_folder_items(
        session,
        query=project_crud.ProjectFolderItemsQuery(
            item_type=item_type,
            name_contains=normalized_name,
            sort_by=sort_by,
            sort_order=sort_order,
        ),
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        folder_id=folder_id,
        limit=limit,
        offset=offset,
    )
    items = await _build_project_folder_items(
        session=session,
        user=user,
        item_refs=page.items,
        include_last_runs=include_last_runs,
        access_scope=access_scope,
    )
    return ProjectSearchPageSchema(
        items=items,
        total=page.total,
        limit=limit,
        offset=offset,
        has_more=build_has_more(offset=offset, page_size=len(items), total=page.total),
    )


async def get_projects_route_impl(
        *,
        session: AsyncSession,
        user: UserRecord,
        sort_by: Literal["default", "updated_at"],
        sort_order: Literal["asc", "desc"],
) -> list[ProjectReadSchema]:
    base_stmt = (
        sa.select(ProjectRecord)
        .where(ProjectRecord.is_deleted == False)
    )

    base_stmt = base_stmt.where(
        *build_owner_or_org_filters(
            user=user,
            organization_column=ProjectRecord.organization_id,
            owner_column=ProjectRecord.user_id,
        )
    )
    if sort_by == "updated_at":
        base_stmt = base_stmt.order_by(
            ProjectRecord.updated_at.asc() if sort_order == "asc" else ProjectRecord.updated_at.desc(),
            ProjectRecord.id,
        )

    projects = (await session.execute(base_stmt)).scalars().all()
    if not projects:
        return []

    user_emails = await project_crud.get_user_emails_by_ids(
        session,
        user_ids=[project.user_id for project in projects],
    )
    last_runs_by_project_id = await _get_last_runs_by_project_id(
        session=session,
        user=user,
        project_ids=[project.id for project in projects],
    )
    return [
        _project_to_read_schema(
            project,
            user_email=user_emails.get(project.user_id),
            last_runs_by_project_id=last_runs_by_project_id,
        )
        for project in projects
    ]


async def create_project_route_impl(
        *,
        data: ProjectCreateSchema,
        session: AsyncSession,
        user: UserRecord,
) -> ProjectReadSchema:
    new_id = str(uuid.uuid4())
    date_now = datetime.now(tz=UTC)

    payload = data.model_dump()
    if payload.get("variables") is not None:
        payload["variables"] = normalize_project_variables_storage_map(
            payload["variables"],
            allow_legacy=False,
        )
    await _validate_project_folder_target(
        session=session,
        user=user,
        folder_id=payload.get("folder_id"),
        project_owner_user_id=user.id,
        organization_id=user.organization_id,
    )

    project = ProjectRecord(
        id=new_id,
        created_at=date_now,
        updated_at=date_now,
        user_id=user.id,
        organization_id=user.organization_id,
        **payload,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return ProjectReadSchema(**project.model_dump(exclude_unset=True, exclude_none=True))


async def get_project_by_id_route_impl(
        *,
        project: ProjectRecord,
        session: AsyncSession,
        user: UserRecord,
) -> ProjectReadSchema:
    last_runs_by_project_id = await _get_last_runs_by_project_id(
        session=session,
        user=user,
        project_ids=[project.id],
    )
    user_emails = await project_crud.get_user_emails_by_ids(
        session,
        user_ids=[project.user_id],
    )
    return _project_to_read_schema(
        project,
        user_email=user_emails.get(project.user_id),
        last_runs_by_project_id=last_runs_by_project_id,
    )


async def update_project_route_impl(
        *,
        data: ProjectUpdateSchema,
        session: AsyncSession,
        user: UserRecord,
        project: ProjectRecord,
) -> ProjectReadSchema:
    update_payload = data.model_dump(exclude_unset=True)
    if update_payload.get("variables") is not None:
        update_payload["variables"] = normalize_project_variables_storage_map(
            update_payload["variables"],
            allow_legacy=False,
        )
    if "folder_id" in update_payload:
        await _validate_project_folder_target(
            session=session,
            user=user,
            folder_id=update_payload["folder_id"],
            project_owner_user_id=project.user_id,
            organization_id=project.organization_id,
        )
    project.sqlmodel_update(update_payload)

    project.updated_at = datetime.now(tz=UTC)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return ProjectReadSchema(**project.model_dump())


async def delete_projects_route_impl(
        *,
        data: ProjectsDeleteSchema,
        session: AsyncSession,
        user: UserRecord,
) -> CommonResponse:
    project_ids = list(dict.fromkeys(data.project_ids))
    accessible_project_ids = await _get_accessible_project_ids_for_deletion(
        session=session,
        user=user,
        project_ids=project_ids,
    )
    if not accessible_project_ids:
        raise exc.ProjectsNotFoundException(project_ids)

    deleted_at = datetime.now(tz=UTC)
    await session.execute(
        sa.update(ProjectRecord)
        .where(ProjectRecord.id.in_(accessible_project_ids))
        .values(is_deleted=True, updated_at=deleted_at)
    )
    await session.commit()

    return CommonResponse(
        success=True,
        message=f"Projects deleted: {len(accessible_project_ids)}",
    )


async def delete_project_route_impl(
        *,
        session: AsyncSession,
        project: ProjectRecord,
) -> CommonResponse:
    project.is_deleted = True
    project.updated_at = datetime.now(tz=UTC)

    session.add(project)
    await session.commit()
    await session.refresh(project)

    return CommonResponse(
        success=True,
        message="Project successfully deleted.",
    )
