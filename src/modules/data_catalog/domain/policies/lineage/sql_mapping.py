"""Сопоставление результата SQL-lineage с полями сущностей каталога."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ...entities import DatasetField
from ...lineage import (
    ColumnLineage,
    LineageRef,
    PortColumns,
    SqlLineageResult,
    SqlSchemaHint,
    SqlSourceColumn,
)
from ...types import DiagnosticReason, FieldStatus, LineageOp, PortStatus, SqlColumnKind

_CASE_INSENSITIVE_DIALECTS = frozenset({"postgresql", "mysql", "mssql", "oracle"})


def match_field_name(name: str, fields: Sequence[DatasetField], dialect: str | None) -> DatasetField | None:
    """Точное совпадение, затем регистронезависимое для диалектов, которые сами приводят регистр."""
    for item in fields:
        if item.name == name:
            return item
    if dialect in _CASE_INSENSITIVE_DIALECTS:
        lowered = name.lower()
        for item in fields:
            if item.name.lower() == lowered:
                return item
    return None


def active_fields(fields: Sequence[DatasetField]) -> list[DatasetField]:
    return [item for item in fields if item.status is not FieldStatus.MISSING]


def build_schema_hint(
    references: Mapping[str, str],
    fields_by_dataset: Mapping[str, Sequence[DatasetField]],
) -> SqlSchemaHint:
    tables = {
        reference: tuple(item.name for item in active_fields(fields_by_dataset.get(dataset_id, ())))
        for reference, dataset_id in references.items()
    }
    return SqlSchemaHint(tables={ref: cols for ref, cols in tables.items() if cols})


def sql_lineage_to_port_columns(
    result: SqlLineageResult,
    references: Mapping[str, str],
    fields_by_dataset: Mapping[str, Sequence[DatasetField]],
    dialect: str | None,
) -> PortColumns:
    """Колонки SQL-ноды со ссылками на поля сущностей; неизвестные источники → deps_unknown."""
    if not result.supported:
        return PortColumns.unresolved(DiagnosticReason.LINEAGE_SQL_UNSUPPORTED, result.error)

    columns: list[ColumnLineage] = []
    partial = False
    for item in result.columns:
        deps: list[LineageRef] = []
        unknown = item.unknown_sources
        for source in item.sources:
            dataset_id = references.get(source.reference)
            if dataset_id is None:
                unknown = True
                continue
            field = match_field_name(source.column, active_fields(fields_by_dataset.get(dataset_id, ())), dialect)
            if field is None:
                unknown = True
                continue
            ref = LineageRef.dataset_field(dataset_id, field.id)
            if ref not in deps:
                deps.append(ref)
        op, template = _op_for(item.kind, item.name, item.sources)
        if unknown:
            partial = True
        details: dict[str, object] = {"template": template}
        if item.expression and item.kind in (SqlColumnKind.EXPRESSION, SqlColumnKind.AGGREGATE):
            details["expression"] = item.expression
        if item.kind is SqlColumnKind.UNION:
            details["count"] = len(deps)
        if op is LineageOp.RENAME and item.sources:
            details["source"] = item.sources[0].column
        columns.append(
            ColumnLineage(name=item.name, op=op, deps=tuple(deps), deps_unknown=unknown, details=details)
        )

    status = PortStatus.PARTIALLY_RESOLVED if partial else PortStatus.RESOLVED
    detail = "some SQL sources are not catalog fields" if partial else None
    return PortColumns(columns=tuple(columns), status=status, detail=detail)


def _op_for(  # noqa: PLR0911 - одна ветка на вид SQL-колонки
    kind: SqlColumnKind, name: str, sources: Sequence[SqlSourceColumn]
) -> tuple[LineageOp, str]:
    if kind is SqlColumnKind.AGGREGATE:
        return LineageOp.AGGREGATE, "lineage.source.sql.aggregate"
    if kind is SqlColumnKind.UNION:
        return LineageOp.MERGE, "lineage.source.sql.union"
    if kind is SqlColumnKind.LITERAL:
        return LineageOp.COMPUTE, "lineage.source.sql.literal"
    if kind is SqlColumnKind.UNKNOWN:
        return LineageOp.UNKNOWN, "lineage.unknown.sql"
    if kind is SqlColumnKind.COLUMN:
        if len(sources) == 1 and sources[0].column.lower() != name.lower():
            return LineageOp.RENAME, "lineage.source.sql.column"
        return LineageOp.PASS, "lineage.source.sql.column"
    return LineageOp.COMPUTE, "lineage.source.sql.expression"
