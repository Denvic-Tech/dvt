from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.project.infra.db_models import ProjectFolderRecord, ProjectRecord

PROJECT_FOLDER_ITEM_TYPES = Literal["folder", "project"]
PROJECT_SEARCH_ITEM_TYPES = Literal["all", "folder", "project"]
PROJECT_ITEMS_SORT_FIELDS = Literal["default", "updated_at"]
PROJECT_ITEMS_SORT_ORDERS = Literal["asc", "desc"]


@dataclass(frozen=True, slots=True)
class ProjectFolderItemRef:
    item_type: PROJECT_FOLDER_ITEM_TYPES
    item_id: str


@dataclass(frozen=True, slots=True)
class ProjectFolderItemsPage:
    total: int
    items: list[ProjectFolderItemRef]


@dataclass(frozen=True, slots=True)
class ProjectFolderItemsQuery:
    item_type: PROJECT_SEARCH_ITEM_TYPES = "all"
    name_contains: str | None = None
    sort_by: PROJECT_ITEMS_SORT_FIELDS = "default"
    sort_order: PROJECT_ITEMS_SORT_ORDERS = "desc"


def _scope_filters(
    model,
    *,
    organization_id: str | None,
    owner_user_id: str | None,
) -> list[sa.ColumnExpressionArgument[bool]]:
    filters: list[sa.ColumnExpressionArgument[bool]] = []
    if organization_id is not None:
        filters.append(model.organization_id == organization_id)
    if owner_user_id is not None:
        filters.append(model.user_id == owner_user_id)
    return filters


def _parent_filter(column, parent_id: str | None) -> sa.ColumnExpressionArgument[bool]:
    if parent_id is None:
        return column.is_(None)
    return column == parent_id


def _item_select(
    *,
    item_type: PROJECT_FOLDER_ITEM_TYPES,
    model,
    parent_column,
    name_column,
    id_column,
    created_at_column,
    updated_at_column,
    parent_id: str | None,
    apply_parent_filter: bool,
    organization_id: str | None,
    owner_user_id: str | None,
    name_contains: str | None = None,
):
    filters = [
        model.is_deleted == False,
        *_scope_filters(
            model,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
        ),
    ]
    if apply_parent_filter:
        filters.append(_parent_filter(parent_column, parent_id))
    if name_contains is not None:
        filters.append(name_column.ilike(f"%{name_contains}%"))

    return sa.select(
        sa.literal(item_type).label("item_type"),
        id_column.label("item_id"),
        name_column.label("name"),
        created_at_column.label("created_at"),
        updated_at_column.label("updated_at"),
    ).where(*filters)


def _build_page_order_by(
    items,
    *,
    sort_by: PROJECT_ITEMS_SORT_FIELDS,
    sort_order: PROJECT_ITEMS_SORT_ORDERS,
) -> list:
    type_order = sa.case((items.c.item_type == "folder", 0), else_=1)
    if sort_by == "updated_at":
        sort_expression = items.c.updated_at.asc() if sort_order == "asc" else items.c.updated_at.desc()
        return [
            sort_expression,
            type_order,
            sa.func.lower(items.c.name),
            items.c.created_at.desc(),
            items.c.item_id,
        ]

    return [
        type_order,
        sa.func.lower(items.c.name),
        items.c.created_at,
        items.c.item_id,
    ]


async def get_folder_by_id(
    session: AsyncSession,
    *,
    folder_id: str,
    organization_id: str | None = None,
    owner_user_id: str | None = None,
) -> ProjectFolderRecord | None:
    stmt = sa.select(ProjectFolderRecord).where(
        ProjectFolderRecord.id == folder_id,
        ProjectFolderRecord.is_deleted == False,
        *_scope_filters(
            ProjectFolderRecord,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
        ),
    )
    return (await session.execute(stmt)).scalars().first()


async def get_folder_depth(
    session: AsyncSession,
    *,
    folder_id: str,
    organization_id: str,
    max_depth: int,
) -> int | None:
    depth = 1
    current_id: str | None = folder_id
    seen: set[str] = set()

    while current_id is not None:
        if current_id in seen or depth > max_depth:
            return None
        seen.add(current_id)

        parent_id = (
            await session.execute(
                sa.select(ProjectFolderRecord.parent_id).where(
                    ProjectFolderRecord.id == current_id,
                    ProjectFolderRecord.organization_id == organization_id,
                    ProjectFolderRecord.is_deleted == False,
                )
            )
        ).scalar_one_or_none()
        current_id = parent_id
        if current_id is not None:
            depth += 1

    return depth


async def folder_has_children(
    session: AsyncSession,
    *,
    folder_id: str,
) -> bool:
    folders_exists = await session.execute(
        sa.select(sa.literal(True)).where(
            ProjectFolderRecord.parent_id == folder_id,
            ProjectFolderRecord.is_deleted == False,
        ).limit(1)
    )
    if folders_exists.scalar_one_or_none():
        return True

    projects_exists = await session.execute(
        sa.select(sa.literal(True)).where(
            ProjectRecord.folder_id == folder_id,
            ProjectRecord.is_deleted == False,
        ).limit(1)
    )
    return bool(projects_exists.scalar_one_or_none())


async def get_descendant_folder_ids(
    session: AsyncSession,
    *,
    folder_id: str,
    organization_id: str,
    max_depth: int,
) -> set[str]:
    pending = [folder_id]
    descendants: set[str] = set()
    depth = 0

    while pending and depth <= max_depth:
        rows = (
            await session.execute(
                sa.select(ProjectFolderRecord.id).where(
                    ProjectFolderRecord.parent_id.in_(pending),
                    ProjectFolderRecord.organization_id == organization_id,
                    ProjectFolderRecord.is_deleted == False,
                )
            )
        ).scalars().all()
        pending = [row for row in rows if row not in descendants]
        descendants.update(pending)
        depth += 1

    return descendants


async def get_folder_subtree_depth(
    session: AsyncSession,
    *,
    folder_id: str,
    organization_id: str,
    max_depth: int,
) -> int:
    current_level = [folder_id]
    depth = 1
    seen = {folder_id}

    while current_level and depth <= max_depth:
        rows = (
            await session.execute(
                sa.select(ProjectFolderRecord.id).where(
                    ProjectFolderRecord.parent_id.in_(current_level),
                    ProjectFolderRecord.organization_id == organization_id,
                    ProjectFolderRecord.is_deleted == False,
                )
            )
        ).scalars().all()
        next_level = [row for row in rows if row not in seen]
        if not next_level:
            break
        seen.update(next_level)
        current_level = next_level
        depth += 1

    return depth


async def get_project_folder_items_page(
    session: AsyncSession,
    *,
    parent_id: str | None,
    organization_id: str | None,
    owner_user_id: str | None,
    limit: int,
    offset: int,
    sort_by: PROJECT_ITEMS_SORT_FIELDS = "default",
    sort_order: PROJECT_ITEMS_SORT_ORDERS = "desc",
) -> ProjectFolderItemsPage:
    folders = _item_select(
        item_type="folder",
        model=ProjectFolderRecord,
        parent_column=ProjectFolderRecord.parent_id,
        name_column=ProjectFolderRecord.name,
        id_column=ProjectFolderRecord.id,
        created_at_column=ProjectFolderRecord.created_at,
        updated_at_column=ProjectFolderRecord.updated_at,
        parent_id=parent_id,
        apply_parent_filter=True,
        organization_id=organization_id,
        owner_user_id=owner_user_id,
    )
    projects = _item_select(
        item_type="project",
        model=ProjectRecord,
        parent_column=ProjectRecord.folder_id,
        name_column=ProjectRecord.name,
        id_column=ProjectRecord.id,
        created_at_column=ProjectRecord.created_at,
        updated_at_column=ProjectRecord.updated_at,
        parent_id=parent_id,
        apply_parent_filter=True,
        organization_id=organization_id,
        owner_user_id=owner_user_id,
    )

    items = folders.union_all(projects).subquery()
    total = (
        await session.execute(sa.select(sa.func.count()).select_from(items))
    ).scalar_one()

    page_rows = (
        await session.execute(
            sa.select(items.c.item_type, items.c.item_id)
            .order_by(*_build_page_order_by(items, sort_by=sort_by, sort_order=sort_order))
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return ProjectFolderItemsPage(
        total=total,
        items=[
            ProjectFolderItemRef(item_type=row.item_type, item_id=row.item_id)
            for row in page_rows
        ],
    )


async def search_project_folder_items(
    session: AsyncSession,
    *,
    query: ProjectFolderItemsQuery,
    folder_id: str | None,
    organization_id: str | None,
    owner_user_id: str | None,
    limit: int,
    offset: int,
) -> ProjectFolderItemsPage:
    selects = []

    if query.item_type in ("all", "folder"):
        selects.append(
            _item_select(
                item_type="folder",
                model=ProjectFolderRecord,
                parent_column=ProjectFolderRecord.parent_id,
                name_column=ProjectFolderRecord.name,
                id_column=ProjectFolderRecord.id,
                created_at_column=ProjectFolderRecord.created_at,
                updated_at_column=ProjectFolderRecord.updated_at,
                parent_id=folder_id,
                apply_parent_filter=folder_id is not None,
                organization_id=organization_id,
                owner_user_id=owner_user_id,
                name_contains=query.name_contains,
            )
        )

    if query.item_type in ("all", "project"):
        selects.append(
            _item_select(
                item_type="project",
                model=ProjectRecord,
                parent_column=ProjectRecord.folder_id,
                name_column=ProjectRecord.name,
                id_column=ProjectRecord.id,
                created_at_column=ProjectRecord.created_at,
                updated_at_column=ProjectRecord.updated_at,
                parent_id=folder_id,
                apply_parent_filter=folder_id is not None,
                organization_id=organization_id,
                owner_user_id=owner_user_id,
                name_contains=query.name_contains,
            )
        )

    if not selects:
        return ProjectFolderItemsPage(total=0, items=[])

    items = selects[0].subquery() if len(selects) == 1 else selects[0].union_all(*selects[1:]).subquery()
    total = (
        await session.execute(sa.select(sa.func.count()).select_from(items))
    ).scalar_one()

    page_rows = (
        await session.execute(
            sa.select(items.c.item_type, items.c.item_id)
            .order_by(
                *_build_page_order_by(
                    items,
                    sort_by=query.sort_by,
                    sort_order=query.sort_order,
                )
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return ProjectFolderItemsPage(
        total=total,
        items=[
            ProjectFolderItemRef(item_type=row.item_type, item_id=row.item_id)
            for row in page_rows
        ],
    )


async def get_folders_by_ids(
    session: AsyncSession,
    *,
    folder_ids: Sequence[str],
    organization_id: str | None,
    owner_user_id: str | None,
) -> list[ProjectFolderRecord]:
    if not folder_ids:
        return []
    stmt = sa.select(ProjectFolderRecord).where(
        ProjectFolderRecord.id.in_(folder_ids),
        ProjectFolderRecord.is_deleted == False,
        *_scope_filters(
            ProjectFolderRecord,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
        ),
    )
    return list((await session.execute(stmt)).scalars().all())
