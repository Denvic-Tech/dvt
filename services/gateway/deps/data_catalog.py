from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.deps.db_catalog import get_catalog_use_cases

from src.modules.data_catalog import DataCatalogUseCases, build_data_catalog_use_cases
from src.modules.data_catalog.domain import DB_TABLE_KIND, CatalogViewer, SchemaActor, ViewerScope
from src.modules.data_catalog.infra import DbCatalogDatasetSchemaSource
from src.modules.user.infra.db_models import UserRecord
from src.utils.access_control import get_access_scope

import config


def build_viewer(user: UserRecord) -> CatalogViewer:
    scope = get_access_scope(user)
    if scope.organization_id is None:
        viewer_scope = ViewerScope.ALL
    elif scope.owner_user_id is None:
        viewer_scope = ViewerScope.ORGANIZATION
    else:
        viewer_scope = ViewerScope.OWN
    return CatalogViewer(
        user_id=user.id,
        organization_id=user.organization_id,
        scope=viewer_scope,
    )


def build_schema_actor(user: UserRecord) -> SchemaActor:
    return SchemaActor(id=user.id, organization_id=user.organization_id, role=str(user.role))


def get_data_catalog_use_cases(
    session: AsyncSession,
    redis: Redis | None = None,
) -> DataCatalogUseCases:
    schema_sources = (
        {DB_TABLE_KIND: DbCatalogDatasetSchemaSource(get_catalog_use_cases(redis))}
        if redis is not None
        else None
    )
    return build_data_catalog_use_cases(
        session=session,
        schema_sources=schema_sources,
        schema_sync_ttl_sec=config.DATA_CATALOG.SCHEMA_SYNC_TTL_SEC,
    )
