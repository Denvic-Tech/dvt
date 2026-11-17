"""Производная видимость сущностей: через проекты владельца или его connection'ы."""

from __future__ import annotations

import sqlalchemy as sa

from src.modules.db_connection.infra.db_models import DVTStoredConnectionRecord
from src.modules.project.infra.db_models import ProjectRecord

from ...domain import CatalogViewer, ViewerScope
from ..db_models import DatasetConnectionRecord, DatasetLinkRecord, DatasetRecord


def dataset_visibility_filters(viewer: CatalogViewer) -> list[sa.ColumnElement[bool]]:
    if viewer.scope is ViewerScope.ALL:
        return []

    filters: list[sa.ColumnElement[bool]] = [
        DatasetRecord.organization_id == viewer.organization_id,
    ]
    if viewer.scope is ViewerScope.ORGANIZATION:
        return filters

    via_projects = sa.exists().where(
        DatasetLinkRecord.dataset_id == DatasetRecord.id,
        DatasetLinkRecord.project_id == ProjectRecord.id,
        ProjectRecord.user_id == viewer.user_id,
        ProjectRecord.is_deleted.is_(False),
    )
    via_connections = sa.exists().where(
        DatasetConnectionRecord.dataset_id == DatasetRecord.id,
        DatasetConnectionRecord.connection_id == DVTStoredConnectionRecord.id,
        DVTStoredConnectionRecord.user_id == viewer.user_id,
        DVTStoredConnectionRecord.deleted_at.is_(None),
    )
    filters.append(sa.or_(via_projects, via_connections))
    return filters


def project_visibility_filters(viewer: CatalogViewer) -> list[sa.ColumnElement[bool]]:
    filters: list[sa.ColumnElement[bool]] = [ProjectRecord.is_deleted.is_(False)]
    if viewer.scope is ViewerScope.ALL:
        return filters
    filters.append(ProjectRecord.organization_id == viewer.organization_id)
    if viewer.scope is ViewerScope.OWN:
        filters.append(ProjectRecord.user_id == viewer.user_id)
    return filters


def connection_visibility_filters(viewer: CatalogViewer) -> list[sa.ColumnElement[bool]]:
    filters: list[sa.ColumnElement[bool]] = [DVTStoredConnectionRecord.deleted_at.is_(None)]
    if viewer.scope is ViewerScope.ALL:
        return filters
    filters.append(DVTStoredConnectionRecord.organization_id == viewer.organization_id)
    if viewer.scope is ViewerScope.OWN:
        filters.append(DVTStoredConnectionRecord.user_id == viewer.user_id)
    return filters
