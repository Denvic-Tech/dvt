from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from typing import Any

import dask.dataframe as dd
from sqlalchemy.ext.asyncio import AsyncSession

from .domain import (
    DatasetSchemaSource,
    LineageTextRenderer,
    ObservationOutcome,
    ProjectRef,
    RebuildResult,
    ReconcileSummary,
    SourceKindRegistry,
    TableSchema,
    default_registry,
)
from .domain.policies import build_builtin_rules
from .flow import (
    BuildSchema,
    ConfirmFieldRename,
    ExplainField,
    GetDataset,
    GetDatasetUsage,
    GetFieldDependents,
    GetNodeFields,
    GetProjectColumns,
    OnProjectVariablesChanged,
    ProjectionFreshnessProvider,
    RebuildProjectCatalogProjection,
    RebuildProjectLineage,
    ReconcileCatalogProjections,
    RecordObservedPortSchemas,
    RecordObservedSchema,
    RefreshDatasetSchema,
    SearchDatasets,
    SetDatasetDescriptions,
    SetNodeColumnDescriptions,
    SyncDatasetSchema,
)
from .infra import (
    DataFrameSchemaMapper,
    DataFrameSchemaMapping,
    JsonLineageTemplateRenderer,
    NodeDslColumnRulePlanner,
    NodeDslExpressionResolver,
    NodeDslPortTypeGateway,
    SQLAlchemyCatalogProjectSource,
    SQLAlchemyDatasetConnectionRepository,
    SQLAlchemyDatasetFieldRepository,
    SQLAlchemyDatasetLinkRepository,
    SQLAlchemyDatasetRepository,
    SQLAlchemyNodeColumnAnnotationRepository,
    SQLAlchemyNodePortObservationRepository,
    SQLAlchemyProjectGraphGateway,
    SQLAlchemyProjectionRepository,
    SQLConnectionLocatorGateway,
    SqlglotColumnLineageExtractor,
    SqlglotTableReferenceExtractor,
    build_observation,
    build_port_observations,
)

DEFAULT_SCHEMA_SYNC_TTL_SEC = 300
DEFAULT_RECONCILE_BATCH_SIZE = 100

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


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
    record_observed_ports: RecordObservedPortSchemas
    get_node_fields: GetNodeFields
    explain_field: ExplainField
    get_field_dependents: GetFieldDependents
    set_node_column_descriptions: SetNodeColumnDescriptions
    get_project_columns: GetProjectColumns
    sync_schema: SyncDatasetSchema | None = None
    refresh_schema: RefreshDatasetSchema | None = None


def build_data_catalog_use_cases(
    *,
    session: AsyncSession,
    schema_sources: Mapping[str, DatasetSchemaSource] | None = None,
    schema_sync_ttl_sec: int = DEFAULT_SCHEMA_SYNC_TTL_SEC,
    sources: SourceKindRegistry | None = None,
    lineage_renderer: LineageTextRenderer | None = None,
) -> DataCatalogUseCases:
    """schema_sources: источник схемы на каждый kind сущности; без него sync/refresh недоступны."""
    registry = sources or default_registry()
    renderer = lineage_renderer or _default_renderer()
    datasets = SQLAlchemyDatasetRepository(session)
    fields = SQLAlchemyDatasetFieldRepository(session)
    connections = SQLAlchemyDatasetConnectionRepository(session)
    links = SQLAlchemyDatasetLinkRepository(session)
    projections = SQLAlchemyProjectionRepository(session)
    annotations = SQLAlchemyNodeColumnAnnotationRepository(session)
    observations = SQLAlchemyNodePortObservationRepository(session)
    graph_gateway = SQLAlchemyProjectGraphGateway(session)
    planner = NodeDslColumnRulePlanner()
    lineage_builder = RebuildProjectLineage(
        fields=fields,
        port_types=NodeDslPortTypeGateway(),
        rules=build_builtin_rules(planner),
        sql_lineage=SqlglotColumnLineageExtractor(),
        planner=planner,
        observations=observations,
    )

    rebuild = RebuildProjectCatalogProjection(
        datasets=datasets,
        connections=connections,
        links=links,
        projections=projections,
        graph_gateway=graph_gateway,
        connection_locator=SQLConnectionLocatorGateway(session),
        expression_resolver=NodeDslExpressionResolver(),
        sql_extractor=SqlglotTableReferenceExtractor(),
        sources=registry,
        lineage_builder=lineage_builder,
    )
    sync_schema = (
        SyncDatasetSchema(
            datasets=datasets,
            fields=fields,
            connections=connections,
            schema_sources=schema_sources,
            ttl_seconds=schema_sync_ttl_sec,
            projections=projections,
        )
        if schema_sources
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
        record_observed_ports=RecordObservedPortSchemas(
            observations=observations, projections=projections, graph_gateway=graph_gateway
        ),
        record_observed=RecordObservedSchema(
            datasets=datasets,
            fields=fields,
            connections=connections,
            links=links,
            sources=registry,
            projections=projections,
        ),
        get_node_fields=GetNodeFields(
            projections=projections,
            fields=fields,
            renderer=renderer,
            freshness=freshness,
            annotations=annotations,
            datasets=datasets,
        ),
        explain_field=ExplainField(
            projections=projections,
            fields=fields,
            renderer=renderer,
            freshness=freshness,
            annotations=annotations,
        ),
        get_field_dependents=GetFieldDependents(
            datasets=datasets, fields=fields, links=links, projections=projections, freshness=freshness
        ),
        set_node_column_descriptions=SetNodeColumnDescriptions(
            annotations=annotations,
            graph_gateway=graph_gateway,
            projections=projections,
            freshness=freshness,
        ),
        get_project_columns=GetProjectColumns(
            projections=projections,
            fields=fields,
            datasets=datasets,
            annotations=annotations,
            freshness=freshness,
        ),
        sync_schema=sync_schema,
        refresh_schema=refresh_schema,
    )


def _default_renderer() -> LineageTextRenderer:
    import config

    return JsonLineageTemplateRenderer(config.PROJECT.LOCALES_DIR)


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
    task_id: str | None = None,
) -> ObservationOutcome | None:
    """Точка входа воркера: схема таблицы Read-ноды и состав колонок всех DataFrame-выходов
    попадают в каталог. Без commit."""
    observation = build_observation(node, metadata, project_id=project_id)
    ports = build_port_observations(node, metadata, project_id=project_id, task_id=task_id)
    if observation is None and not ports:
        return None
    use_cases = build_data_catalog_use_cases(session=session)
    outcome = ObservationOutcome()
    if observation is not None:
        outcome = await use_cases.record_observed.execute(observation)
    port_count = await use_cases.record_observed_ports.execute(ports) if ports else 0
    return replace(outcome, port_count=port_count)


async def reconcile_catalog_projections(
    *,
    session_factory: SessionFactory,
    force: bool = False,
    dry_run: bool = False,
    batch_size: int = DEFAULT_RECONCILE_BATCH_SIZE,
    organization_id: str | None = None,
    project_ids: Sequence[str] | None = None,
) -> ReconcileSummary:
    """Сверка проекций для старта Gateway и backfill: каждый проект в своей транзакции."""

    async def rebuild_one(project: ProjectRef, force_rebuild: bool) -> RebuildResult:
        async with session_factory() as session:
            try:
                result = await rebuild_project_catalog_projection(
                    session=session,
                    project_id=project.project_id,
                    organization_id=project.organization_id,
                    force=force_rebuild,
                    raise_on_error=True,
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return result

    async with session_factory() as listing_session:
        use_case = ReconcileCatalogProjections(
            projects=SQLAlchemyCatalogProjectSource(listing_session),
            rebuild_one=rebuild_one,
            batch_size=batch_size,
        )
        return await use_case.execute(
            force=force,
            dry_run=dry_run,
            organization_id=organization_id,
            project_ids=project_ids,
        )
