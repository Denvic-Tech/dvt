from __future__ import annotations

import re
from typing import Any

import sqlalchemy as sa
from db_connection import AccessDeniedError, ConnectionNotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.deps.db_connection import get_connection_service

from src.modules.project.infra.db_models import ProjectRecord
from src.utils.access_control import get_access_scope

from .auth import MCPPrincipal
from .errors import denied

_SECRET_FIELD_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "private_key",
    "access_key",
    "connection_url",
    "url",
    "uri",
    "dsn",
    "ca_cert",
)


def sanitized_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if any(part in normalized for part in _SECRET_FIELD_PARTS):
                continue
            result[str(key)] = sanitized_mapping(item)
        return result
    if isinstance(value, (list, tuple)):
        return [sanitized_mapping(item) for item in value]
    if isinstance(value, str):
        if re.match(r"^[a-z][a-z0-9+.-]*://[^/\s]+@", value, flags=re.IGNORECASE):
            return "<redacted-credential-url>"
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def connection_public_payload(connection) -> dict[str, Any]:
    connection_kind = str(connection.kind).lower()
    connection_type = str(connection.type).lower()
    return {
        "id": connection.id,
        "name": connection.name,
        "kind": str(connection.kind),
        "type": str(connection.type),
        "driver": connection.driver,
        "properties": sanitized_mapping(connection.properties),
        "labels": sanitized_mapping(connection.labels),
        "metadata": sanitized_mapping(connection.metadata),
        "capabilities": {
            "database_catalog": connection_kind == "sql",
            "ddl_create": connection_kind == "sql",
            "readonly_sql": connection_kind == "sql"
            and connection_type in {"postgres", "mysql", "oracle", "clickhouse"},
            "storage_list": connection_kind == "file"
            and connection_type in {"s3", "smbprotocol", "ftp", "sftp"},
            "storage_preview": connection_kind == "file"
            and connection_type in {"s3", "smbprotocol", "ftp", "sftp"},
        },
        "updated_at": connection.updated_at.isoformat(),
    }


def is_excluded_connection(connection) -> bool:
    return str(connection.kind).lower() == "queue" or str(connection.type).lower() == "kafka"


def _project_filters(principal: MCPPrincipal) -> list:
    access_scope = get_access_scope(principal.user)
    filters = [ProjectRecord.is_deleted.is_(False)]
    if access_scope.organization_id is not None:
        filters.append(ProjectRecord.organization_id == access_scope.organization_id)
    if access_scope.owner_user_id is not None:
        filters.append(ProjectRecord.user_id == access_scope.owner_user_id)
    if principal.token.access_scope.projects.mode.value == "selected":
        ids = tuple(principal.token.access_scope.projects.ids)
        filters.append(ProjectRecord.id.in_(ids) if ids else sa.false())
    return filters


async def list_accessible_projects(
    session: AsyncSession,
    principal: MCPPrincipal,
    *,
    search: str | None = None,
) -> list[ProjectRecord]:
    filters = _project_filters(principal)
    if search:
        filters.append(ProjectRecord.name.ilike(f"%{search.strip()}%"))
    return list(
        (
            await session.execute(
                sa.select(ProjectRecord)
                .where(*filters)
                .order_by(ProjectRecord.updated_at.desc(), ProjectRecord.id.asc())
            )
        )
        .scalars()
        .all()
    )


async def get_accessible_project(
    session: AsyncSession,
    principal: MCPPrincipal,
    project_id: str,
    *,
    for_update: bool = False,
) -> ProjectRecord:
    if not principal.allows_project(project_id):
        raise denied("project")
    statement = sa.select(ProjectRecord).where(
        ProjectRecord.id == project_id,
        *_project_filters(principal),
    )
    if for_update:
        statement = statement.with_for_update()
    project = (await session.execute(statement)).scalar_one_or_none()
    if project is None:
        raise denied("project")
    return project


async def get_accessible_connection(principal: MCPPrincipal, connection_id: str):
    if not principal.allows_connection(connection_id):
        raise denied("connection")
    try:
        connection = await get_connection_service().get(
            connection_id,
            actor=principal.user,
        )
    except (AccessDeniedError, ConnectionNotFoundError):
        raise denied("connection") from None
    if connection.deleted_at is not None or is_excluded_connection(connection):
        raise denied("connection")
    return connection
