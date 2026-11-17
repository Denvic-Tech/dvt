from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from src.crud import project as project_crud
from src.modules.data_catalog.facade import rebuild_project_catalog_projection
from src.modules.file_storage.infra.db_models import DVTServiceFileObjectRecord
from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord
from src.modules.project.infra.db_models import (
    ProjectFolderRecord,
    ProjectRecord,
    ProjectScheduleRecord,
)
from src.modules.project_transfer.domain.entities import (
    GraphSnapshot,
    ProjectFile,
    ProjectMeta,
    SourceFolder,
    SourceProject,
    TargetFolder,
    TargetProject,
)
from src.modules.project_transfer.domain.policies import PROJECT_FOLDER_MAX_DEPTH
from src.modules.project_transfer.domain.repositories import (
    ProjectTransferReadRepository,
    ProjectTransferWriteRepository,
)
from src.modules.project_transfer.domain.value_objects import TransferActor
from src.modules.project_transfer.infra import graph_cloner


def _scope_filters(actor: TransferActor, organization_column, owner_column) -> list:
    if actor.has_global_access:
        return []
    filters = [organization_column == actor.organization_id]
    if not actor.is_admin:
        filters.append(owner_column == actor.user_id)
    return filters


def _project_to_source(project: ProjectRecord) -> SourceProject:
    return SourceProject(
        id=project.id,
        folder_id=project.folder_id,
        organization_id=project.organization_id,
        meta=ProjectMeta(
            name=project.name,
            store_enabled=project.store_enabled,
            ttl_time=project.ttl_time,
            workers_count=project.workers_count,
        ),
        variables=dict(project.variables) if project.variables else None,
    )


class SQLProjectTransferReadRepository(ProjectTransferReadRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_projects(
        self,
        project_ids: Sequence[str],
        *,
        actor: TransferActor,
    ) -> list[SourceProject]:
        if not project_ids:
            return []
        rows = (
            await self._session.execute(
                sa.select(ProjectRecord)
                .where(
                    ProjectRecord.id.in_(list(project_ids)),
                    ProjectRecord.is_deleted.is_(False),
                    *_scope_filters(actor, ProjectRecord.organization_id, ProjectRecord.user_id),
                )
                .order_by(ProjectRecord.name, ProjectRecord.id)
            )
        ).scalars().all()
        return [_project_to_source(row) for row in rows]

    async def get_folder_subtrees(
        self,
        folder_ids: Sequence[str],
        *,
        actor: TransferActor,
    ) -> tuple[list[SourceFolder], list[SourceProject]]:
        if not folder_ids:
            return [], []
        folder_filters = _scope_filters(actor, ProjectFolderRecord.organization_id, ProjectFolderRecord.user_id)
        roots = (
            await self._session.execute(
                sa.select(ProjectFolderRecord).where(
                    ProjectFolderRecord.id.in_(list(folder_ids)),
                    ProjectFolderRecord.is_deleted.is_(False),
                    *folder_filters,
                )
            )
        ).scalars().all()

        folders: dict[str, ProjectFolderRecord] = {root.id: root for root in roots}
        pending = list(folders)
        depth = 0
        while pending and depth <= PROJECT_FOLDER_MAX_DEPTH:
            children = (
                await self._session.execute(
                    sa.select(ProjectFolderRecord).where(
                        ProjectFolderRecord.parent_id.in_(pending),
                        ProjectFolderRecord.is_deleted.is_(False),
                        *folder_filters,
                    )
                )
            ).scalars().all()
            pending = [child.id for child in children if child.id not in folders]
            folders.update({child.id: child for child in children if child.id not in folders})
            depth += 1

        projects = (
            await self._session.execute(
                sa.select(ProjectRecord)
                .where(
                    ProjectRecord.folder_id.in_(list(folders)),
                    ProjectRecord.is_deleted.is_(False),
                    *_scope_filters(actor, ProjectRecord.organization_id, ProjectRecord.user_id),
                )
                .order_by(ProjectRecord.name, ProjectRecord.id)
            )
        ).scalars().all() if folders else []

        root_ids = {root.id for root in roots}
        source_folders = [
            SourceFolder(
                id=folder.id,
                name=folder.name,
                parent_id=None if folder.id in root_ids else folder.parent_id,
                organization_id=folder.organization_id,
            )
            for folder in sorted(folders.values(), key=lambda item: (item.name, item.id))
        ]
        return source_folders, [_project_to_source(project) for project in projects]

    async def read_graph(self, project_id: str) -> GraphSnapshot:
        return await graph_cloner.read_graph_snapshot(self._session, project_id)

    async def read_files(self, project_id: str, *, with_content: bool) -> list[ProjectFile]:
        columns = [
            DVTServiceFileObjectRecord.parent_path,
            DVTServiceFileObjectRecord.name,
            DVTServiceFileObjectRecord.is_dir,
            DVTServiceFileObjectRecord.size,
            DVTServiceFileObjectRecord.sha256,
            DVTServiceFileObjectRecord.content_type,
        ]
        if with_content:
            columns.append(DVTServiceFileObjectRecord.content)
        rows = (
            await self._session.execute(
                sa.select(*columns)
                .where(DVTServiceFileObjectRecord.project_id == project_id)
                .order_by(DVTServiceFileObjectRecord.parent_path, DVTServiceFileObjectRecord.name)
            )
        ).all()
        files = []
        for row in rows:
            storage_path = f"{row.parent_path}/{row.name}".strip("/")
            files.append(
                ProjectFile(
                    storage_path=storage_path,
                    is_dir=row.is_dir,
                    size=row.size,
                    sha256=row.sha256,
                    content_type=row.content_type,
                    content=row.content if with_content and not row.is_dir else None,
                )
            )
        return files


class SQLProjectTransferWriteRepository(ProjectTransferWriteRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_target_folder(self, folder_id: str, *, actor: TransferActor) -> TargetFolder | None:
        folder = (
            await self._session.execute(
                sa.select(ProjectFolderRecord).where(
                    ProjectFolderRecord.id == folder_id,
                    ProjectFolderRecord.is_deleted.is_(False),
                    *_scope_filters(actor, ProjectFolderRecord.organization_id, ProjectFolderRecord.user_id),
                )
            )
        ).scalars().first()
        if folder is None:
            return None
        depth = await project_crud.get_folder_depth(
            self._session,
            folder_id=folder.id,
            organization_id=folder.organization_id,
            max_depth=PROJECT_FOLDER_MAX_DEPTH,
        )
        return TargetFolder(
            id=folder.id,
            organization_id=folder.organization_id,
            depth=depth if depth is not None else PROJECT_FOLDER_MAX_DEPTH,
        )

    async def get_target_project(
        self,
        project_id: str,
        *,
        actor: TransferActor,
        lock: bool = False,
    ) -> TargetProject | None:
        stmt = sa.select(ProjectRecord).where(
            ProjectRecord.id == project_id,
            ProjectRecord.is_deleted.is_(False),
            *_scope_filters(actor, ProjectRecord.organization_id, ProjectRecord.user_id),
        )
        if lock:
            stmt = stmt.with_for_update()
        project = (await self._session.execute(stmt)).scalars().first()
        if project is None:
            return None
        has_graph = (
            await self._session.execute(
                sa.select(sa.literal(True)).where(GraphNodeRecord.project_id == project.id).limit(1)
            )
        ).scalar_one_or_none() is not None
        has_schedule = (
            await self._session.execute(
                sa.select(sa.literal(True)).where(ProjectScheduleRecord.project_id == project.id).limit(1)
            )
        ).scalar_one_or_none() is not None
        return TargetProject(
            id=project.id,
            name=project.name,
            organization_id=project.organization_id,
            user_id=project.user_id,
            variables=dict(project.variables) if project.variables else None,
            has_graph=has_graph,
            has_schedule=has_schedule,
        )

    async def create_folder(
        self,
        *,
        name: str,
        parent_id: str | None,
        actor: TransferActor,
        now: datetime,
    ) -> str:
        folder = ProjectFolderRecord(
            id=str(uuid.uuid4()),
            name=name,
            parent_id=parent_id,
            user_id=actor.user_id,
            organization_id=actor.organization_id,
            is_deleted=False,
            created_at=now,
            updated_at=now,
        )
        self._session.add(folder)
        await self._session.flush()
        return folder.id

    async def create_project(
        self,
        *,
        meta: ProjectMeta,
        folder_id: str | None,
        variables: dict[str, dict[str, Any]] | None,
        actor: TransferActor,
        now: datetime,
    ) -> str:
        project = ProjectRecord(
            id=str(uuid.uuid4()),
            name=meta.name,
            user_id=actor.user_id,
            organization_id=actor.organization_id,
            is_deleted=False,
            folder_id=folder_id,
            store_enabled=meta.store_enabled,
            ttl_time=meta.ttl_time,
            workers_count=meta.workers_count,
            variables=variables,
            created_at=now,
            updated_at=now,
        )
        self._session.add(project)
        await self._session.flush()
        return project.id

    async def set_variables(self, project_id: str, variables: dict[str, dict[str, Any]] | None) -> None:
        project = await self._session.get(ProjectRecord, project_id)
        if project is None:
            return
        project.variables = variables
        flag_modified(project, "variables")
        self._session.add(project)
        await self._session.flush()

    async def clear_graph(self, project_id: str) -> list[str]:
        removed = (
            await self._session.execute(
                sa.select(GraphNodeRecord.ui_id).where(GraphNodeRecord.project_id == project_id)
            )
        ).scalars().all()
        await graph_cloner.delete_graph(self._session, project_id)
        return list(removed)

    async def insert_graph(
        self,
        project_id: str,
        snapshot: GraphSnapshot,
        *,
        owner_user_id: str,
        organization_id: str,
        now: datetime,
    ) -> None:
        await graph_cloner.insert_graph_snapshot(
            self._session,
            snapshot,
            project_id=project_id,
            user_id=owner_user_id,
            organization_id=organization_id,
            now=now,
        )

    async def insert_files(
        self,
        project_id: str,
        files: Sequence[ProjectFile],
        *,
        organization_id: str,
        now: datetime,
    ) -> None:
        if not files:
            return
        values = [
            {
                "id": str(uuid.uuid4()),
                "organization_id": organization_id,
                "project_id": project_id,
                "parent_path": file.parent_path,
                "name": file.name,
                "is_dir": file.is_dir,
                "content": None if file.is_dir else file.content,
                "content_type": file.content_type,
                "size": 0 if file.is_dir else len(file.content or b""),
                "sha256": file.sha256,
                "created_at": now,
                "updated_at": now,
            }
            for file in files
        ]
        await self._session.execute(sa.insert(DVTServiceFileObjectRecord.__table__), values)

    async def mark_graph_changed(
        self,
        project_id: str,
        *,
        organization_id: str,
        node_ui_ids: Sequence[str],
        removed_node_ui_ids: Sequence[str] = (),
    ) -> None:
        await project_crud.mark_project_graph_dirty(
            self._session,
            project_id=project_id,
            organization_id=organization_id,
            node_ids=list(node_ui_ids),
            removed_node_ids=list(removed_node_ui_ids),
        )

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def rebuild_catalog(self, project_id: str, *, organization_id: str) -> None:
        try:
            await rebuild_project_catalog_projection(
                session=self._session,
                project_id=project_id,
                organization_id=organization_id,
                force=True,
            )
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
