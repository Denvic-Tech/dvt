"""Статический проход по сохранённому графу: сущности, связи с connection'ами и dataset_links."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
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
    GraphInputValue,
    LocatorKind,
    ProjectCatalogProjection,
    ProjectGraphGateway,
    ProjectionDiagnostic,
    ProjectionRepository,
    ProjectionStamp,
    ProjectionStatus,
    RawLocator,
    RebuildResult,
    ResolvedVia,
    SqlReferenceExtractionError,
    SqlTableReferenceExtractor,
)
from ...domain.policies import (
    LocatorCandidate,
    build_physical_key,
    canonical_dialect,
    extract_locator_candidates,
    is_projection_current,
    normalize_locator,
    select_table_candidates,
    sql_table_ref_to_raw_locator,
    variables_fingerprint,
)
from ..exceptions import ProjectionRebuildFailedError

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
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._datasets = datasets
        self._connections = connections
        self._links = links
        self._projections = projections
        self._graph = graph_gateway
        self._connection_locator = connection_locator
        self._expressions = expression_resolver
        self._sql = sql_extractor
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
        candidates, diagnostics = extract_locator_candidates(snapshot)
        now = self._clock()
        depends_on_variables = False
        links: dict[tuple[str, str, str], DatasetLink] = {}
        locator_cache: dict[str, ConnectionLocator | None] = {}

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

            dialect = canonical_dialect(connection.dialect)
            if dialect is None:
                diagnostics.append(
                    _diagnostic(candidate, DiagnosticReason.UNSUPPORTED_DIALECT, connection.dialect)
                )
                continue

            try:
                raw_locators, resolved_via, used_variables = self._resolve_locators(
                    candidate=candidate,
                    dialect=dialect,
                    project_variables=project_variables,
                )
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
                depends_on_variables = depends_on_variables or reason is DiagnosticReason.SQL_TEMPLATE_UNRESOLVED
                diagnostics.append(_diagnostic(candidate, reason, str(exc)))
                continue

            depends_on_variables = depends_on_variables or used_variables

            for raw in raw_locators:
                locator = normalize_locator(raw, connection, dialect=dialect)
                if not locator.table:
                    diagnostics.append(
                        _diagnostic(candidate, DiagnosticReason.LOCATOR_INPUT_MISSING, "empty table name")
                    )
                    continue
                physical_key = build_physical_key(locator)
                dataset = await self._datasets.upsert(
                    Dataset(
                        id=self._new_id(),
                        organization_id=organization_id,
                        locator=locator,
                        physical_key=physical_key,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await self._connections.touch(
                    dataset.id, connection.id, connection.revision, now
                )
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
                    resolved_via=resolved_via,
                    graph_revision=snapshot.graph_revision,
                    created_at=now,
                    updated_at=now,
                )

        await self._links.replace_for_project(project_id, list(links.values()))
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
        return RebuildResult(status="ok", projection=projection, link_count=len(links))

    def _resolve_locators(
        self,
        *,
        candidate: LocatorCandidate,
        dialect: str,
        project_variables: Mapping[str, Any],
    ) -> tuple[list[RawLocator], ResolvedVia, bool]:
        spec = candidate.spec
        used_variables = False

        def value_of(name: str) -> Any:
            nonlocal used_variables
            item = candidate.inputs.get(name)
            if item is None:
                return None
            if item.kind == "expr":
                used_variables = True
                return self._expressions.resolve(
                    str(item.value), item.expression_kind or "template", project_variables
                )
            return item.value

        if candidate.kind is LocatorKind.EXPLICIT:
            raw = RawLocator(
                table=_as_text(value_of(spec.table_input)) or "",
                schema=_as_text(value_of(spec.schema_input)),
                database=_as_text(value_of(spec.database_input)),
            )
            resolved_via = ResolvedVia.EXPRESSION if used_variables else ResolvedVia.CONST
            return [raw], resolved_via, used_variables

        if candidate.kind is LocatorKind.SQL:
            return self._resolve_sql(
                sql=_as_text(value_of(spec.sql_input)) or "",
                candidate=candidate,
                dialect=dialect,
                project_variables=project_variables,
                used_variables=used_variables,
            )

        if spec.sql_input in candidate.inputs:
            return self._resolve_sql(
                sql=_as_text(value_of(spec.sql_input)) or "",
                candidate=candidate,
                dialect=dialect,
                project_variables=project_variables,
                used_variables=used_variables,
            )

        manual = value_of(spec.manual_variables_input)
        raw_locators: list[RawLocator] = []
        if isinstance(manual, Mapping):
            for entry in manual.values():
                if not isinstance(entry, Mapping):
                    continue
                table = _as_text(entry.get("table_name"))
                if not table:
                    continue
                raw_locators.append(
                    RawLocator(
                        table=table,
                        schema=_as_text(entry.get("schema_name")),
                        database=_as_text(entry.get("database_name")),
                    )
                )
        resolved_via = ResolvedVia.EXPRESSION if used_variables else ResolvedVia.CONST
        return raw_locators, resolved_via, used_variables

    def _resolve_sql(
        self,
        *,
        sql: str,
        candidate: LocatorCandidate,
        dialect: str,
        project_variables: Mapping[str, Any],
        used_variables: bool,
    ) -> tuple[list[RawLocator], ResolvedVia, bool]:
        references = self._sql.extract(sql, dialect, project_variables)
        tables = select_table_candidates(
            references.tables,
            cte_names=references.cte_names,
            excluded_names=candidate.dataframe_input_names,
        )
        raw_locators = [sql_table_ref_to_raw_locator(ref, dialect=dialect) for ref in tables]
        return raw_locators, ResolvedVia.SQL, used_variables or references.used_project_variables

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
    candidate: LocatorCandidate,
    reason: DiagnosticReason,
    detail: str | None = None,
) -> ProjectionDiagnostic:
    return ProjectionDiagnostic(
        node_id=candidate.node_id,
        node_name=candidate.node_name,
        reason=reason,
        detail=detail,
    )


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, GraphInputValue):
        value = value.value
    text = str(value).strip()
    return text or None
