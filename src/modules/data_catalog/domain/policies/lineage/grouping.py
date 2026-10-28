"""Проектный вид колонок: группы по origin.

Группа это только способ показать: все колонки одной цепочки PASS/RENAME/SOURCE делят origin,
а описание по-прежнему хранится у конкретной колонки ноды или у поля сущности. Вхождение с
`declared` не на самом origin считается переопределением: ниже по цепочке наследуется уже его текст.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime

from ...entities import Dataset, DatasetField
from ...lineage import (
    GLOBAL_SCOPE,
    PROJECT_SCOPE,
    ColumnGroup,
    ColumnOccurrence,
    ColumnRow,
    DescriptionTarget,
    LineageRef,
    NodeColumnAnnotation,
    ProjectLineage,
    ResolvedDescription,
    UnresolvedPort,
)
from ...types import DiagnosticReason, LineageOp, LineageProvenance, PortStatus
from .description_resolution import DescriptionResolver
from .index import LineageIndex

_TRANSPARENT_OPS = (LineageOp.PASS, LineageOp.RENAME, LineageOp.SOURCE)


def description_attribution(
    description: ResolvedDescription,
    fields: Mapping[str, DatasetField],
    annotations: Mapping[str, NodeColumnAnnotation],
) -> tuple[str | None, datetime | None]:
    """Автор и время текста: у аннотации всегда, у поля только для собственного описания."""
    if description.text is None or description.source is None:
        return None, None
    annotation = annotations.get(description.source.key)
    if annotation is not None:
        return annotation.description_updated_by, annotation.updated_at
    field = fields.get(description.source.key)
    if field is not None and field.description:
        return field.description_updated_by, field.description_updated_at
    return None, None


def column_depth(index: LineageIndex, ref: LineageRef, origin: LineageRef) -> int:
    """Число хопов от колонки до origin по прозрачным операциям; обрыв цепочки даёт пройденные хопы."""
    depth = 0
    current = ref
    seen: set[str] = {ref.key}
    while current.key != origin.key and not current.is_dataset_field:
        found = index.column(current)
        if found is None:
            break
        _, column = found
        if column.op not in _TRANSPARENT_OPS or len(column.deps) != 1 or column.deps_unknown:
            break
        depth += 1
        current = column.deps[0]
        if current.key in seen:
            break
        seen.add(current.key)
    return depth


def group_columns_by_origin(
    index: LineageIndex,
    resolver: DescriptionResolver,
    *,
    fields: Mapping[str, DatasetField],
    datasets: Mapping[str, Dataset],
    annotations: Mapping[str, NodeColumnAnnotation],
) -> tuple[ColumnGroup, ...]:
    """fields и annotations по ключу ссылки, datasets по dataset_id."""
    buckets: dict[str, list[ColumnOccurrence]] = {}
    origins: dict[str, LineageRef] = {}
    node_names: dict[str, str] = {}

    for port, column in index.columns.values():
        ref = port.ref(column.name)
        origin = column.origin or ref
        description = resolver.resolve(ref)
        updated_by, updated_at = description_attribution(description, fields, annotations)
        occurrence = ColumnOccurrence(
            ref=ref,
            node_id=port.node_id,
            node_name=port.node_name,
            port=port.port,
            role=port.role,
            column=column.name,
            op=column.op,
            deps=column.deps,
            deps_unknown=column.deps_unknown,
            depth=column_depth(index, ref, origin),
            description=description,
            is_override=_is_override(ref, origin, description),
            description_updated_by=updated_by,
            description_updated_at=updated_at,
        )
        buckets.setdefault(origin.key, []).append(occurrence)
        origins[origin.key] = origin
        node_names[port.node_id] = port.node_name

    groups: list[ColumnGroup] = []
    for key, occurrences in buckets.items():
        origin = origins[key]
        description = resolver.resolve(origin)
        updated_by, updated_at = description_attribution(description, fields, annotations)
        field = fields.get(origin.key) if origin.is_dataset_field else None
        dataset = datasets.get(origin.dataset_id or "") if origin.is_dataset_field else None
        groups.append(
            ColumnGroup(
                origin=origin,
                description=description,
                occurrences=tuple(
                    sorted(occurrences, key=lambda item: (item.depth, item.node_id, item.port, item.column))
                ),
                dataset_id=origin.dataset_id,
                dataset_location=dataset.location if dataset is not None else None,
                field_name=field.name if field is not None else None,
                origin_node_name=None if origin.is_dataset_field else node_names.get(origin.node_id or ""),
                description_updated_by=updated_by,
                description_updated_at=updated_at,
            )
        )
    return tuple(sorted(groups, key=_group_order))


def _is_override(ref: LineageRef, origin: LineageRef, description: ResolvedDescription) -> bool:
    """Текст написан на этой самой колонке, и она не origin: ниже наследуется уже он."""
    return (
        description.provenance is LineageProvenance.DECLARED
        and description.source is not None
        and description.source.key == ref.key
        and ref.key != origin.key
    )


def _group_order(group: ColumnGroup) -> tuple:
    origin = group.origin
    if origin.is_dataset_field:
        return (0, group.dataset_location or "", group.field_name or "", origin.key)
    return (1, group.origin_node_name or "", origin.node_id or "", origin.port or "", origin.column or "")


_NEW_ORIGIN_OPS = (LineageOp.COMPUTE, LineageOp.AGGREGATE, LineageOp.MERGE)


def build_column_rows(groups: tuple[ColumnGroup, ...]) -> tuple[ColumnRow, ...]:
    """Строки общего слоя: вхождения группы делятся по (имя колонки, источник описания).

    Старт отрезка это вхождение с минимальной глубиной. Ветвление цепочки не рвёт строку.
    `depends_on` заполняется только у строк, начинающихся новым origin (compute/aggregate/merge).
    """
    rows: list[ColumnRow] = []
    row_by_ref: dict[str, str] = {}
    for group in groups:
        buckets: dict[tuple[str, str | None], list[ColumnOccurrence]] = {}
        for occurrence in group.occurrences:
            source = occurrence.description.source
            key = (occurrence.column, source.key if source is not None else None)
            buckets.setdefault(key, []).append(occurrence)
        for (name, _), occurrences in buckets.items():
            start = occurrences[0]
            row = ColumnRow(
                id=start.ref.key,
                name=name,
                origin=group.origin,
                start=start.ref,
                description=start.description,
                occurrences=tuple(occurrences),
                targets=_targets(group, start),
                dataset_id=group.dataset_id,
                dataset_location=group.dataset_location,
                field_name=group.field_name,
                origin_node_name=group.origin_node_name,
                description_updated_by=start.description_updated_by,
                description_updated_at=start.description_updated_at,
                is_rename=start.op is LineageOp.RENAME,
                renamed_from=_renamed_from(start),
                is_refinement=start.is_override and start.op is LineageOp.PASS,
            )
            for occurrence in occurrences:
                row_by_ref[occurrence.ref.key] = row.id
            rows.append(row)

    return tuple(_with_dependencies(row, row_by_ref) for row in rows)


def _with_dependencies(row: ColumnRow, row_by_ref: Mapping[str, str]) -> ColumnRow:
    start = row.occurrences[0]
    if start.op not in _NEW_ORIGIN_OPS:
        return row
    depends_on: dict[str, None] = {}
    for dep in start.deps:
        target = row_by_ref.get(dep.key)
        if target is not None and target != row.id:
            depends_on.setdefault(target, None)
    return replace(row, depends_on=tuple(depends_on))


def _targets(group: ColumnGroup, start: ColumnOccurrence) -> tuple[DescriptionTarget, ...]:
    targets = [
        DescriptionTarget(scope=PROJECT_SCOPE, node_id=start.node_id, port=start.port, column=start.column)
    ]
    if group.origin.is_dataset_field and start.op is LineageOp.SOURCE:
        # Первый отрезок цепочки из таблицы: текст можно записать и в поле сущности (глобально).
        targets.append(
            DescriptionTarget(
                scope=GLOBAL_SCOPE,
                dataset_id=group.origin.dataset_id,
                field_id=group.origin.field_id,
                field_name=group.field_name,
            )
        )
    return tuple(targets)


def _renamed_from(start: ColumnOccurrence) -> str | None:
    if start.op is not LineageOp.RENAME or len(start.deps) != 1:
        return None
    dep = start.deps[0]
    return None if dep.is_dataset_field else dep.column


def collect_unresolved_ports(lineage: ProjectLineage) -> tuple[UnresolvedPort, ...]:
    """Порты, у которых каталог не знает колонок.

    Порты с наблюдённой схемой и всё, что от них наследует `lineage_schema_observed`, сюда не
    попадают: их колонки известны, неизвестно только происхождение, и это видно по самим колонкам.
    """
    return tuple(
        UnresolvedPort(
            node_id=port.node_id,
            node_name=port.node_name,
            port=port.port,
            role=port.role,
            status=port.status,
            reason=port.reason,
            detail=port.detail,
        )
        for port in lineage.ports
        if port.status is not PortStatus.RESOLVED
        and port.reason is not DiagnosticReason.LINEAGE_SCHEMA_OBSERVED
    )


def collect_orphaned_annotations(
    index: LineageIndex,
    annotations: Mapping[str, NodeColumnAnnotation],
) -> tuple[NodeColumnAnnotation, ...]:
    """Аннотации, чьих колонок больше нет в lineage проекта."""
    orphaned = [item for key, item in annotations.items() if key not in index.columns]
    return tuple(sorted(orphaned, key=lambda item: (item.node_id, item.port, item.column)))
