from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import dask.dataframe as dd
from sqlalchemy.ext.asyncio import AsyncSession

from .domain import DatasetSchemaSource, ObservationOutcome, RebuildResult, TableSchema
from .flow import (
    BuildSchema,
    ConfirmFieldRename,
    GetDataset,
    GetDatasetUsage,
    OnProjectVariablesChanged,
    ProjectionFreshnessProvider,
    RebuildProjectCatalogProjection,
    RecordObservedSchema,
    RefreshDatasetSchema,
    SearchDatasets,
    SetDatasetDescriptions,
    SyncDatasetSchema,
)
from .infra import (
    DataFrameSchemaMapper,
    DataFrameSchemaMapping,
    NodeDslExpressionResolver,
    SQLAlchemyDatasetConnectionRepository,
    SQLAlchemyDatasetFieldRepository,
    SQLAlchemyDatasetLinkRepository,
    SQLAlchemyDatasetRepository,
    SQLAlchemyProjectGraphGateway,
    SQLAlchemyProjectionRepository,
    SQLConnectionLocatorGateway,
    SqlglotTableReferenceExtractor,
    build_observation,
)

DEFAULT_SCHEMA_SYNC_TTL_SEC = 300


def build_table_schema_from_dataframe(
    *,
    dataframe: dd.DataFrame,
    mapping: DataFrameSchemaMapping,
) -> TableSchema:
    columns = DataFrameSchemaMapper().to_columns(dataframe=dataframe, mapping=mapping)
    return BuildSchema().execute(columns)


@dataclass(frozen=True, slots=True)
class DataCatalogUseCases:
    rebuild: RebuildProjectCatalogProjection
    on_variables_changed: OnProjectVariablesChanged
    search: SearchDatasets
    get_dataset: GetDataset
    get_usage: GetDatasetUsage
    set_descriptions: SetDatasetDescriptions
    confirm_rename: ConfirmFieldRename
    record_observed: RecordObservedSchema
    sync_schema: SyncDatasetSchema | None = None
    refresh_schema: RefreshDatasetSchema | None = None


def build_data_catalog_use_cases(
    *,
    session: AsyncSession,
    schema_source: DatasetSchemaSource | None = None,
    schema_sync_ttl_sec: int = DEFAULT_SCHEMA_SYNC_TTL_SEC,
) -> DataCatalogUseCases:
    datasets = SQLAlchemyDatasetRepository(session)
    fields = SQLAlchemyDatasetFieldRepository(session)
    connections = SQLAlchemyDatasetConnectionRepository(session)
    links = SQLAlchemyDatasetLinkRepository(session)
    projections = SQLAlchemyProjectionRepository(session)
    graph_gateway = SQLAlchemyProjectGraphGateway(session)

    rebuild = RebuildProjectCatalogProjection(
        datasets=datasets,
        connections=connections,
        links=links,
        projections=projections,
        graph_gateway=graph_gateway,
        connection_locator=SQLConnectionLocatorGateway(session),
        expression_resolver=NodeDslExpressionResolver(),
        sql_extractor=SqlglotTableReferenceExtractor(),
    )
    sync_schema = (
        SyncDatasetSchema(
            datasets=datasets,
            fields=fields,
            connections=connections,
            schema_source=schema_source,
            ttl_seconds=schema_sync_ttl_sec,
        )
        if schema_source is not None
        else None
    )
    refresh_schema = (
        RefreshDatasetSchema(datasets=datasets, links=links, sync_schema=sync_schema)
        if sync_schema is not None
        else None
    )
    freshness = ProjectionFreshnessProvider(
        projections=projections,
        graph_gateway=graph_gateway,
        rebuild=rebuild,
    )
    return DataCatalogUseCases(
        rebuild=rebuild,
        on_variables_changed=OnProjectVariablesChanged(projections=projections, rebuild=rebuild),
        search=SearchDatasets(datasets=datasets, freshness=freshness),
        get_dataset=GetDataset(
            datasets=datasets,
            fields=fields,
            connections=connections,
            ttl_seconds=schema_sync_ttl_sec,
            sync_schema=sync_schema,
        ),
        get_usage=GetDatasetUsage(datasets=datasets, links=links, freshness=freshness),
        set_descriptions=SetDatasetDescriptions(datasets=datasets, fields=fields),
        confirm_rename=ConfirmFieldRename(datasets=datasets, fields=fields),
        record_observed=RecordObservedSchema(
            datasets=datasets,
            fields=fields,
            connections=connections,
            links=links,
        ),
        sync_schema=sync_schema,
        refresh_schema=refresh_schema,
    )


async def rebuild_project_catalog_projection(
    *,
    session: AsyncSession,
    project_id: str,
    organization_id: str,
    force: bool = False,
    raise_on_error: bool = False,
) -> RebuildResult:
    """Точка входа для хуков Gateway и backfill: сборка проекции без источника схемы."""
    use_cases = build_data_catalog_use_cases(session=session)
    return await use_cases.rebuild.execute(
        project_id=project_id,
        organization_id=organization_id,
        force=force,
        raise_on_error=raise_on_error,
    )


async def on_project_variables_changed(
    *,
    session: AsyncSession,
    project_id: str,
    organization_id: str,
) -> RebuildResult:
    use_cases = build_data_catalog_use_cases(session=session)
    return await use_cases.on_variables_changed.execute(
        project_id=project_id,
        organization_id=organization_id,
    )


async def record_observed_node_metadata(
    *,
    session: AsyncSession,
    project_id: str,
    node: Any,
    metadata: Mapping[str, Any] | None,
) -> ObservationOutcome | None:
    """Точка входа воркера: наблюдённая Read-нодой схема попадает в каталог. Без commit."""
    observation = build_observation(node, metadata, project_id=project_id)
    if observation is None:
        return None
    use_cases = build_data_catalog_use_cases(session=session)
    return await use_cases.record_observed.execute(observation)
