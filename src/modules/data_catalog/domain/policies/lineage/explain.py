"""Обход lineage вверх (откуда взялась колонка) и вниз (кто от неё зависит)."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from typing import Any

from ...entities import DatasetField
from ...lineage import ExplainStep, FieldDependent, FieldExplanation, LineageGap, LineageRef
from ...types import ExplainDirection, LineageOp
from .index import LineageIndex

TextRenderer = Callable[[Mapping[str, Any]], str | None]


def explain(
    index: LineageIndex,
    root: LineageRef,
    *,
    direction: ExplainDirection,
    max_depth: int,
    render: TextRenderer,
    fields: Mapping[str, DatasetField] | None = None,
) -> FieldExplanation:
    fields = fields or {}
    steps: list[ExplainStep] = []
    gaps: list[LineageGap] = []
    seen: set[str] = set()
    truncated = False
    queue: deque[tuple[LineageRef, int]] = deque([(root, 0)])

    while queue:
        ref, depth = queue.popleft()
        if ref.key in seen:
            continue
        seen.add(ref.key)
        if ref.is_dataset_field:
            field = fields.get(ref.key)
            steps.append(
                ExplainStep(
                    ref=ref,
                    depth=depth,
                    op=LineageOp.SOURCE,
                    text=render({"template": "lineage.source.field", "field": field.name if field else ref.field_id}),
                    dataset_id=ref.dataset_id,
                    field_id=ref.field_id,
                    field_name=field.name if field else None,
                )
            )
            if direction is ExplainDirection.DOWNSTREAM:
                _enqueue_dependents(index, ref, depth, max_depth, queue)
            continue

        found = index.column(ref)
        if found is None:
            gaps.append(LineageGap(ref=ref, reason="column_not_found"))
            continue
        port, column = found
        steps.append(
            ExplainStep(
                ref=ref,
                depth=depth,
                op=column.op,
                text=render(column.details),
                node_id=port.node_id,
                node_name=port.node_name,
                port=port.port,
                column=column.name,
                deps_unknown=column.deps_unknown,
                deps=column.deps,
            )
        )
        if column.deps_unknown:
            gaps.append(LineageGap(ref=ref, reason="deps_unknown", detail=column.details.get("template")))
        if depth >= max_depth:
            if (direction is ExplainDirection.UPSTREAM and column.deps) or (
                direction is ExplainDirection.DOWNSTREAM and index.dependents.get(ref.key)
            ):
                truncated = True
            continue
        if direction is ExplainDirection.UPSTREAM:
            for dep in column.deps:
                queue.append((dep, depth + 1))
        else:
            _enqueue_dependents(index, ref, depth, max_depth, queue)

    return FieldExplanation(root=root, direction=direction, steps=tuple(steps), gaps=tuple(gaps), truncated=truncated)


def _enqueue_dependents(
    index: LineageIndex,
    ref: LineageRef,
    depth: int,
    max_depth: int,
    queue: deque[tuple[LineageRef, int]],
) -> None:
    if depth >= max_depth:
        return
    for dependent in index.dependents_of(ref):
        queue.append((dependent, depth + 1))


def collect_dependents(index: LineageIndex, root: LineageRef, *, max_depth: int) -> list[FieldDependent]:
    """Все колонки проекта, прямо или транзитивно зависящие от ссылки, в порядке обхода в ширину."""
    result: list[FieldDependent] = []
    seen: set[str] = {root.key}
    queue: deque[tuple[LineageRef, int]] = deque([(root, 0)])
    while queue:
        ref, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for dependent in index.dependents_of(ref):
            if dependent.key in seen:
                continue
            seen.add(dependent.key)
            found = index.column(dependent)
            if found is None:
                continue
            port, column = found
            result.append(
                FieldDependent(
                    project_id=index.project_id,
                    node_id=port.node_id,
                    node_name=port.node_name,
                    port=port.port,
                    column=column.name,
                    op=column.op,
                    depth=depth + 1,
                    ref=dependent,
                )
            )
            queue.append((dependent, depth + 1))
    return result
