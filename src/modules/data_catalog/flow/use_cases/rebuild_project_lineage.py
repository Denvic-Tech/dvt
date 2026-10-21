"""Column-level lineage проекта: seed колонок источников и статический проход по графу."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...domain import (
    ColumnRulePlanner,
    DatasetFieldRepository,
    DiagnosticReason,
    LineageBuildResult,
    NodePortTypeGateway,
    PortColumns,
    ProjectGraphSnapshot,
    ProjectionDiagnostic,
    ResolvedVia,
    SourceSeedContext,
    SqlColumnLineageExtractor,
)
from ...domain.policies import (
    LineageRuleRegistry,
    build_schema_hint,
    derive_project_lineage,
    source_columns_from_fields,
    sql_lineage_to_port_columns,
)

SOURCE_OUTPUT_PORT = "output"


class RebuildProjectLineage:
    def __init__(
        self,
        *,
        fields: DatasetFieldRepository,
        port_types: NodePortTypeGateway,
        rules: LineageRuleRegistry,
        sql_lineage: SqlColumnLineageExtractor | None = None,
        planner: ColumnRulePlanner | None = None,
    ) -> None:
        self._fields = fields
        self._port_types = port_types
        self._rules = rules
        self._sql_lineage = sql_lineage
        self._planner = planner

    async def execute(
        self,
        *,
        snapshot: ProjectGraphSnapshot,
        project_variables: Mapping[str, Any],
        seeds: Sequence[SourceSeedContext],
    ) -> LineageBuildResult:
        dataset_ids = sorted({dataset_id for seed in seeds for dataset_id in seed.dataset_ids})
        fields_by_dataset = await self._fields.list_for_datasets(dataset_ids) if dataset_ids else {}

        seed_ports: dict[str, Mapping[str, PortColumns]] = {}
        diagnostics: list[ProjectionDiagnostic] = []
        for seed in seeds:
            port = self._seed_port(seed, fields_by_dataset, project_variables)
            seed_ports[seed.node_id] = {SOURCE_OUTPUT_PORT: port}
            if port.reason is DiagnosticReason.LINEAGE_SCHEMA_NOT_SYNCED:
                diagnostics.append(
                    ProjectionDiagnostic(
                        node_id=seed.node_id,
                        node_name=seed.node_name,
                        reason=DiagnosticReason.LINEAGE_SCHEMA_NOT_SYNCED,
                        detail=port.detail,
                    )
                )

        lineage, derived_diagnostics = derive_project_lineage(
            snapshot,
            port_types=self._port_types.get_port_types,
            rules=self._rules,
            seeds=seed_ports,
            planner=self._planner,
        )
        diagnostics.extend(derived_diagnostics)
        return LineageBuildResult(lineage=lineage, diagnostics=tuple(diagnostics))

    def _seed_port(
        self,
        seed: SourceSeedContext,
        fields_by_dataset: Mapping[str, list],
        project_variables: Mapping[str, Any],
    ) -> PortColumns:
        if seed.resolved_via is ResolvedVia.SQL:
            if self._sql_lineage is None or not seed.sql or not seed.dialect:
                return PortColumns.unresolved(
                    DiagnosticReason.LINEAGE_SQL_UNSUPPORTED, "SQL lineage extractor is unavailable"
                )
            hint = build_schema_hint(seed.references, fields_by_dataset)
            result = self._sql_lineage.extract(seed.sql, seed.dialect, project_variables, hint)
            return sql_lineage_to_port_columns(result, seed.references, fields_by_dataset, seed.dialect)

        if len(seed.dataset_ids) != 1:
            return PortColumns.unresolved(
                DiagnosticReason.LINEAGE_INPUT_INVALID, "table node resolved to an unexpected number of datasets"
            )
        dataset_id = seed.dataset_ids[0]
        return source_columns_from_fields(dataset_id, fields_by_dataset.get(dataset_id, []), seed.column_filter)
