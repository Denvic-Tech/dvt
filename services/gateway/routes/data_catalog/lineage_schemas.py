"""Домен lineage → транспортные схемы; используется роутами и MCP-обёртками."""

from __future__ import annotations

from src.modules.data_catalog.domain import (
    ExplainStep,
    FieldDependent,
    FieldExplanation,
    LineageGap,
    LineageRef,
    NodeFieldsResult,
    NodeFieldView,
    ResolvedDescription,
)

from .schemas import (
    ExplainStepSchema,
    FieldDependentSchema,
    FieldExplanationSchema,
    LineageGapSchema,
    LineageRefSchema,
    NodeFieldSchema,
    NodeFieldsResponseSchema,
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
        explanation=view.explanation,
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
