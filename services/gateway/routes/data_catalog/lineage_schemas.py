"""Домен lineage → транспортные схемы; используется роутами и MCP-обёртками."""

from __future__ import annotations

from src.modules.data_catalog.domain import (
    ColumnGroup,
    ColumnOccurrence,
    ColumnRow,
    DescriptionTarget,
    ExplainStep,
    FieldDependent,
    FieldExplanation,
    LineageGap,
    LineageRef,
    NodeColumnAnnotation,
    NodeFieldsResult,
    NodeFieldView,
    ProjectColumnsResult,
    ResolvedDescription,
    UnresolvedPort,
)

from .schemas import (
    ColumnGroupSchema,
    ColumnOccurrenceSchema,
    ColumnRowSchema,
    DescriptionTargetSchema,
    ExplainStepSchema,
    FieldDependentSchema,
    FieldExplanationSchema,
    LineageGapSchema,
    LineageRefSchema,
    NodeFieldSchema,
    NodeFieldsResponseSchema,
    OrphanedAnnotationSchema,
    ProjectColumnsResponseSchema,
    ProjectOrphanedAnnotationSchema,
    UnresolvedPortSchema,
)


def ref_to_schema(ref: LineageRef) -> LineageRefSchema:
    return LineageRefSchema(
        key=ref.key,
        kind=ref.kind.value,
        dataset_id=ref.dataset_id,
        field_id=ref.field_id,
        node_id=ref.node_id,
        port=ref.port,
        column=ref.column,
    )


def field_view_to_schema(view: NodeFieldView) -> NodeFieldSchema:
    return NodeFieldSchema(
        name=view.name,
        ref=ref_to_schema(view.ref),
        op=view.op.value,
        origin=ref_to_schema(view.origin),
        deps=[ref_to_schema(dep) for dep in view.deps],
        deps_unknown=view.deps_unknown,
        description=view.description,
        description_provenance=view.provenance.value,
        description_source=ref_to_schema(view.description_source) if view.description_source else None,
        description_updated_by=view.description_updated_by,
        description_updated_at=view.description_updated_at,
        explanation=view.explanation,
        origin_field_name=view.origin_field_name,
        origin_location=view.origin_location,
    )


def orphaned_annotation_to_schema(annotation: NodeColumnAnnotation) -> OrphanedAnnotationSchema:
    return OrphanedAnnotationSchema(
        column=annotation.column,
        description=annotation.description,
        origin_key=annotation.origin_key,
        description_updated_by=annotation.description_updated_by,
        updated_at=annotation.updated_at,
    )


def node_fields_to_schema(result: NodeFieldsResult) -> NodeFieldsResponseSchema:
    return NodeFieldsResponseSchema(
        project_id=result.project_id,
        node_id=result.node_id,
        node_name=result.node_name,
        port=result.port,
        role=result.role,
        status=result.status.value,
        reason=result.reason.value if result.reason else None,
        detail=result.detail,
        available_ports=list(result.available_ports),
        fields=[field_view_to_schema(view) for view in result.fields],
        orphaned_annotations=[
            orphaned_annotation_to_schema(item) for item in result.orphaned_annotations
        ],
    )


def occurrence_to_schema(item: ColumnOccurrence) -> ColumnOccurrenceSchema:
    description = item.description
    return ColumnOccurrenceSchema(
        ref=ref_to_schema(item.ref),
        node_id=item.node_id,
        node_name=item.node_name,
        port=item.port,
        role=item.role,
        column=item.column,
        op=item.op.value,
        deps=[ref_to_schema(dep) for dep in item.deps],
        deps_unknown=item.deps_unknown,
        depth=item.depth,
        description=description.text,
        description_provenance=description.provenance.value,
        description_source=ref_to_schema(description.source) if description.source else None,
        description_updated_by=item.description_updated_by,
        description_updated_at=item.description_updated_at,
        is_override=item.is_override,
    )


def group_to_schema(group: ColumnGroup) -> ColumnGroupSchema:
    description = group.description
    return ColumnGroupSchema(
        origin=ref_to_schema(group.origin),
        kind=group.kind,
        dataset_id=group.dataset_id,
        dataset_location=group.dataset_location,
        field_name=group.field_name,
        origin_node_name=group.origin_node_name,
        description=description.text,
        description_provenance=description.provenance.value,
        description_source=ref_to_schema(description.source) if description.source else None,
        description_updated_by=group.description_updated_by,
        description_updated_at=group.description_updated_at,
        override_count=group.override_count,
        occurrences=[occurrence_to_schema(item) for item in group.occurrences],
    )


def target_to_schema(target: DescriptionTarget) -> DescriptionTargetSchema:
    return DescriptionTargetSchema(
        scope=target.scope,
        node_id=target.node_id,
        port=target.port,
        column=target.column,
        dataset_id=target.dataset_id,
        field_id=target.field_id,
        field_name=target.field_name,
    )


def row_to_schema(row: ColumnRow) -> ColumnRowSchema:
    description = row.description
    return ColumnRowSchema(
        id=row.id,
        name=row.name,
        origin=ref_to_schema(row.origin),
        start=ref_to_schema(row.start),
        kind=row.kind,
        dataset_id=row.dataset_id,
        dataset_location=row.dataset_location,
        field_name=row.field_name,
        origin_node_name=row.origin_node_name,
        description=description.text,
        description_provenance=description.provenance.value,
        description_source=ref_to_schema(description.source) if description.source else None,
        description_updated_by=row.description_updated_by,
        description_updated_at=row.description_updated_at,
        is_rename=row.is_rename,
        renamed_from=row.renamed_from,
        is_refinement=row.is_refinement,
        targets=[target_to_schema(target) for target in row.targets],
        depends_on=list(row.depends_on),
        node_count=row.node_count,
        occurrences=[occurrence_to_schema(item) for item in row.occurrences],
    )


def unresolved_port_to_schema(port: UnresolvedPort) -> UnresolvedPortSchema:
    return UnresolvedPortSchema(
        node_id=port.node_id,
        node_name=port.node_name,
        port=port.port,
        role=port.role,
        status=port.status.value,
        reason=port.reason.value if port.reason else None,
        detail=port.detail,
    )


def project_columns_to_schema(result: ProjectColumnsResult) -> ProjectColumnsResponseSchema:
    return ProjectColumnsResponseSchema(
        project_id=result.project_id,
        lineage_available=result.lineage_available,
        truncated=result.truncated,
        rows=[row_to_schema(row) for row in result.rows],
        groups=[group_to_schema(group) for group in result.groups],
        unresolved_ports=[unresolved_port_to_schema(port) for port in result.unresolved_ports],
        orphaned_annotations=[
            ProjectOrphanedAnnotationSchema(
                node_id=item.node_id,
                port=item.port,
                **orphaned_annotation_to_schema(item).model_dump(),
            )
            for item in result.orphaned_annotations
        ],
    )


def step_to_schema(step: ExplainStep) -> ExplainStepSchema:
    return ExplainStepSchema(
        ref=ref_to_schema(step.ref),
        depth=step.depth,
        op=step.op.value,
        text=step.text,
        node_id=step.node_id,
        node_name=step.node_name,
        port=step.port,
        column=step.column,
        deps_unknown=step.deps_unknown,
        dataset_id=step.dataset_id,
        field_id=step.field_id,
        field_name=step.field_name,
        deps=[ref_to_schema(dep) for dep in step.deps],
    )


def gap_to_schema(gap: LineageGap) -> LineageGapSchema:
    return LineageGapSchema(ref=ref_to_schema(gap.ref), reason=gap.reason, detail=gap.detail)


def explanation_to_schema(explanation: FieldExplanation) -> FieldExplanationSchema:
    description: ResolvedDescription | None = explanation.description
    return FieldExplanationSchema(
        root=ref_to_schema(explanation.root),
        direction=explanation.direction.value,
        description=description.text if description else None,
        description_provenance=description.provenance.value if description else "unknown",
        description_source=(
            ref_to_schema(description.source) if description and description.source else None
        ),
        truncated=explanation.truncated,
        steps=[step_to_schema(step) for step in explanation.steps],
        gaps=[gap_to_schema(gap) for gap in explanation.gaps],
    )


def dependent_to_schema(item: FieldDependent) -> FieldDependentSchema:
    return FieldDependentSchema(
        project_id=item.project_id,
        node_id=item.node_id,
        node_name=item.node_name,
        port=item.port,
        column=item.column,
        op=item.op.value,
        depth=item.depth,
        ref=ref_to_schema(item.ref),
    )
