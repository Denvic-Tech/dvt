"""Статический проход по сохранённому графу: сущности, связи с connection'ами и dataset_links.

Use case не знает о природе источников: ноды находит и адреса вычисляет адаптер вида из
SourceKindRegistry, а здесь остаётся общая оркестрация, штампы и диагностики.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from src.logger import logger

from ...domain import (
    LINEAGE_SCHEMA_VERSION,
    ConnectionLocator,
    ConnectionLocatorGateway,
    Dataset,
    DatasetConnectionRepository,
    DatasetLink,
    DatasetLinkRepository,
    DatasetRepository,
    DiagnosticReason,
    ExpressionResolver,
    ExpressionUnresolvedError,
    LinkDirection,
    ProjectCatalogProjection,
    ProjectGraphGateway,
    ProjectionDiagnostic,
    ProjectionRepository,
    ProjectionStamp,
    ProjectionStatus,
    RebuildResult,
    SourceKindRegistry,
    SourceNotSupportedError,
    SourceSeedContext,
    SqlReferenceExtractionError,
    SqlTableReferenceExtractor,
)
from ...domain.policies import SourceCandidate, is_projection_current, variables_fingerprint
from ..exceptions import ProjectionRebuildFailedError

if TYPE_CHECKING:
    from .rebuild_project_lineage import RebuildProjectLineage

_MAX_ERROR_LENGTH = 2000


class RebuildProjectCatalogProjection:
    def __init__(
        self,
        *,
        datasets: DatasetRepository,
        connections: DatasetConnectionRepository,
        links: DatasetLinkRepository,
        projections: ProjectionRepository,
        graph_gateway: ProjectGraphGateway,
        connection_locator: ConnectionLocatorGateway,
        expression_resolver: ExpressionResolver,
        sql_extractor: SqlTableReferenceExtractor,
        sources: SourceKindRegistry,
        lineage_builder: RebuildProjectLineage | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._lineage_builder = lineage_builder
        self._datasets = datasets
        self._connections = connections
        self._links = links
        self._projections = projections
        self._graph = graph_gateway
        self._connection_locator = connection_locator
        self._expressions = expression_resolver
        self._sql = sql_extractor
        self._sources = sources
        self._clock = clock or (lambda: datetime.now(UTC))
        self._new_id = id_factory or (lambda: str(uuid4()))

    async def execute(
        self,
        *,
        project_id: str,
        organization_id: str,
        force: bool = False,
        raise_on_error: bool = False,
    ) -> RebuildResult:
        stored = await self._projections.get(project_id)
        try:
            return await self._rebuild(
                project_id=project_id,
                organization_id=organization_id,
                stored=stored,
                force=force,
            )
        except Exception as exc:
            logger.exception(
                "Data catalog projection rebuild failed for project {}", project_id
            )
            await self._record_failure(
                project_id=project_id,
                organization_id=organization_id,
                stored=stored,
                error=str(exc)[:_MAX_ERROR_LENGTH],
            )
            if raise_on_error:
                raise ProjectionRebuildFailedError(str(exc)) from exc
            return RebuildResult(status="failed", projection=stored, error=str(exc))

    async def _rebuild(
        self,
        *,
        project_id: str,
        organization_id: str,
        stored: ProjectCatalogProjection | None,
        force: bool,
    ) -> RebuildResult:
        await self._graph.lock_project(project_id, organization_id)
        stamp_source = await self._graph.load_stamp_source(project_id, organization_id)
        if stamp_source is None:
            return RebuildResult(status="skipped", projection=stored)

        current = ProjectionStamp(
            graph_revision=stamp_source.graph_revision,
            variables_fingerprint=variables_fingerprint(stamp_source.variables),
            lineage_schema_version=LINEAGE_SCHEMA_VERSION,
        )
        if not force and is_projection_current(stored, current):
            return RebuildResult(status="skipped", projection=stored)

        snapshot = await self._graph.load_snapshot(project_id, organization_id)
        if snapshot is None:
            return RebuildResult(status="skipped", projection=stored)

        project_variables: Mapping[str, Any] = dict(stamp_source.variables or {})
        now = self._clock()
        diagnostics: list[ProjectionDiagnostic] = []
        depends_on_variables = False
        links: dict[tuple[str, str, str], DatasetLink] = {}
        locator_cache: dict[str, ConnectionLocator | None] = {}
        seeds: list[SourceSeedContext] = []

        for adapter in self._sources.adapters():
            candidates, adapter_diagnostics = adapter.extract_candidates(snapshot)
            diagnostics.extend(adapter_diagnostics)

            for candidate in candidates:
                if candidate.connection_id not in locator_cache:
                    locator_cache[candidate.connection_id] = await self._connection_locator.get_locator(
                        candidate.connection_id, organization_id
                    )
                connection = locator_cache[candidate.connection_id]
                if connection is None or connection.deleted:
                    diagnostics.append(
                        _diagnostic(candidate, DiagnosticReason.CONNECTION_MISSING, candidate.connection_id)
                    )
                    continue

                try:
                    resolved = adapter.resolve(
                        candidate,
                        connection,
                        expressions=self._expressions,
                        sql=self._sql,
                        project_variables=project_variables,
                    )
                except SourceNotSupportedError as exc:
                    diagnostics.append(
                        _diagnostic(candidate, DiagnosticReason.UNSUPPORTED_DIALECT, str(exc))
                    )
                    continue
                except ExpressionUnresolvedError as exc:
                    depends_on_variables = True
                    diagnostics.append(
                        _diagnostic(candidate, DiagnosticReason.EXPRESSION_UNRESOLVED, str(exc))
                    )
                    continue
                except SqlReferenceExtractionError as exc:
                    reason = (
                        DiagnosticReason.SQL_TEMPLATE_UNRESOLVED
                        if str(exc).startswith("template")
                        else DiagnosticReason.SQL_PARSE_FAILED
                    )
                    depends_on_variables = (
                        depends_on_variables or reason is DiagnosticReason.SQL_TEMPLATE_UNRESOLVED
                    )
                    diagnostics.append(_diagnostic(candidate, reason, str(exc)))
                    continue

                diagnostics.extend(resolved.diagnostics)
                depends_on_variables = depends_on_variables or resolved.used_variables

                seed_dataset_ids: list[str] = []
                seed_references: dict[str, str] = {}
                for item in resolved.locators:
                    locator = item.locator
                    dataset = await self._datasets.upsert(
                        Dataset(
                            id=self._new_id(),
                            organization_id=organization_id,
                            locator=locator,
                            physical_key=adapter.build_key(locator),
                            location=adapter.describe(locator),
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    await self._connections.touch(
                        dataset.id, connection.id, connection.revision, now
                    )
                    if dataset.id not in seed_dataset_ids:
                        seed_dataset_ids.append(dataset.id)
                    if item.reference:
                        seed_references[item.reference] = dataset.id
                    link_key = (candidate.node_id, candidate.direction.value, dataset.id)
                    if link_key in links:
                        continue
                    links[link_key] = DatasetLink(
                        id=self._new_id(),
                        dataset_id=dataset.id,
                        project_id=project_id,
                        organization_id=organization_id,
                        node_id=candidate.node_id,
                        node_name=candidate.node_name,
                        direction=candidate.direction,
                        resolved_via=resolved.resolved_via,
                        graph_revision=snapshot.graph_revision,
                        created_at=now,
                        updated_at=now,
                    )

                if candidate.direction is LinkDirection.READ and seed_dataset_ids:
                    seeds.append(
                        SourceSeedContext(
                            node_id=candidate.node_id,
                            node_name=candidate.node_name,
                            dataset_ids=tuple(seed_dataset_ids),
                            resolved_via=resolved.resolved_via,
                            references=seed_references,
                            sql=resolved.sql,
                            dialect=resolved.dialect,
                            column_filter=resolved.column_filter,
                        )
                    )

        await self._links.replace_for_project(project_id, list(links.values()))
        lineage_result = await self._build_lineage(
            project_id=project_id,
            snapshot=snapshot,
            project_variables=project_variables,
            seeds=seeds,
            diagnostics=diagnostics,
        )
        projection = ProjectCatalogProjection(
            project_id=project_id,
            organization_id=organization_id,
            stamp=current,
            built_at=now,
            status=ProjectionStatus.OK,
            depends_on_project_variables=depends_on_variables,
            error=None,
            diagnostics=tuple(diagnostics),
        )
        await self._projections.save(projection)
        await self._projections.save_lineage(
            project_id, lineage_result.lineage if lineage_result is not None else None
        )
        return RebuildResult(
            status="ok",
            projection=projection,
            link_count=len(links),
            port_count=lineage_result.port_count if lineage_result is not None else 0,
            column_count=lineage_result.column_count if lineage_result is not None else 0,
        )

    async def _build_lineage(
        self,
        *,
        project_id: str,
        snapshot,
        project_variables: Mapping[str, Any],
        seeds: list[SourceSeedContext],
        diagnostics: list[ProjectionDiagnostic],
    ):
        """Lineage не валит проекцию: сбой даёт диагностику LINEAGE_FAILED и пустой документ."""
        if self._lineage_builder is None:
            return None
        try:
            result = await self._lineage_builder.execute(
                snapshot=snapshot, project_variables=project_variables, seeds=seeds
            )
        except Exception as exc:
            logger.exception("Data catalog lineage build failed for project {}", project_id)
            diagnostics.append(
                ProjectionDiagnostic(
                    node_id="*",
                    node_name="*",
                    reason=DiagnosticReason.LINEAGE_FAILED,
                    detail=str(exc)[:_MAX_ERROR_LENGTH],
                )
            )
            return None
        diagnostics.extend(result.diagnostics)
        return result

    async def _record_failure(
        self,
        *,
        project_id: str,
        organization_id: str,
        stored: ProjectCatalogProjection | None,
        error: str,
    ) -> None:
        stamp = (
            stored.stamp
            if stored is not None
            else ProjectionStamp(
                graph_revision=-1,
                variables_fingerprint="",
                lineage_schema_version=LINEAGE_SCHEMA_VERSION,
            )
        )
        failed = ProjectCatalogProjection(
            project_id=project_id,
            organization_id=organization_id,
            stamp=stamp,
            built_at=self._clock(),
            status=ProjectionStatus.FAILED,
            depends_on_project_variables=(
                stored.depends_on_project_variables if stored is not None else False
            ),
            error=error,
            diagnostics=stored.diagnostics if stored is not None else (),
        )
        try:
            await self._projections.save(failed)
        except Exception:
            logger.warning(
                "Failed to persist failed catalog projection marker for project {}", project_id
            )


def _diagnostic(
    candidate: SourceCandidate,
    reason: DiagnosticReason,
    detail: str | None = None,
) -> ProjectionDiagnostic:
    return ProjectionDiagnostic(
        node_id=candidate.node_id,
        node_name=candidate.node_name,
        reason=reason,
        detail=detail,
    )
