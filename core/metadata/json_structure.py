from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.types import (
    JSONFlattenCandidate,
    JSONFlattenCandidateKind,
    JSONNodeKind,
    JSONStructureNode,
    JSONStructureStats,
)

from .json_utils import (
    JSON_ARRAY_ITEM_TOKEN,
    build_display_json_path,
    build_machine_json_path,
    json_safe,
)


JSON_SCALAR_NODE_KINDS = frozenset(
    {
        JSONNodeKind.STRING,
        JSONNodeKind.INTEGER,
        JSONNodeKind.NUMBER,
        JSONNodeKind.BOOLEAN,
        JSONNodeKind.NULL,
        JSONNodeKind.UNKNOWN,
    }
)


@dataclass(frozen=True, slots=True)
class JSONStructureLimits:
    max_depth: int = 8
    max_object_children: int = 50
    max_array_items: int = 25
    max_examples: int = 3
    max_total_nodes: int = 500


@dataclass(frozen=True, slots=True)
class JSONInferenceResult:
    root: JSONStructureNode | None
    flatten_candidates: list[JSONFlattenCandidate]
    stats: JSONStructureStats | None
    inferred_schema: dict[str, Any] | None
    structure_truncated: bool


@dataclass(slots=True)
class _ObservedNode:
    name: str
    tokens: tuple[str, ...]
    occurrences: int = 0
    null_occurrences: int = 0
    observed_kinds: set[JSONNodeKind] = field(default_factory=set)
    examples: list[Any] = field(default_factory=list)
    children: dict[str, "_ObservedNode"] = field(default_factory=dict)
    object_observations: int = 0
    array_observations: int = 0
    array_min_items: int | None = None
    array_max_items: int | None = None
    sampled_items: int = 0


@dataclass(slots=True)
class _InferenceState:
    limits: JSONStructureLimits
    nodes_created: int = 0
    truncated: bool = False

    def mark_truncated(self) -> None:
        self.truncated = True

    def create_child(self, parent: _ObservedNode, token: str) -> _ObservedNode | None:
        child = parent.children.get(token)
        if child is not None:
            return child

        if self.nodes_created >= self.limits.max_total_nodes:
            self.mark_truncated()
            return None

        child = _ObservedNode(
            name=token,
            tokens=parent.tokens + (token,),
        )
        parent.children[token] = child
        self.nodes_created += 1
        return child


def infer_json_structure(
    obj: Any,
    *,
    limits: JSONStructureLimits | None = None,
) -> JSONInferenceResult:
    if not isinstance(obj, (dict, list)):
        return JSONInferenceResult(
            root=None,
            flatten_candidates=[],
            stats=None,
            inferred_schema=None,
            structure_truncated=False,
        )

    effective_limits = limits or JSONStructureLimits()
    safe_obj = json_safe(obj)
    state = _InferenceState(limits=effective_limits, nodes_created=1)
    root = _ObservedNode(name="$", tokens=())
    _observe_value(safe_obj, root, depth=0, state=state)
    root_model = _build_structure_node(root, required=True)
    stats = _build_structure_stats(root_model)
    flatten_candidates = _build_flatten_candidates(root_model)
    inferred_schema = _build_inferred_schema(root_model)

    return JSONInferenceResult(
        root=root_model,
        flatten_candidates=flatten_candidates,
        stats=stats,
        inferred_schema=inferred_schema,
        structure_truncated=state.truncated,
    )


def _observe_value(value: Any, node: _ObservedNode, *, depth: int, state: _InferenceState) -> None:
    node.occurrences += 1
    kind = _kind_from_value(value)
    node.observed_kinds.add(kind)

    if value is None:
        node.null_occurrences += 1
        if None not in node.examples and len(node.examples) < state.limits.max_examples:
            node.examples.append(None)
        return

    if kind in JSON_SCALAR_NODE_KINDS:
        if value not in node.examples and len(node.examples) < state.limits.max_examples:
            node.examples.append(value)
        return

    if depth >= state.limits.max_depth:
        state.mark_truncated()
        return

    if kind == JSONNodeKind.OBJECT:
        node.object_observations += 1
        keys = list(value.keys())
        if len(keys) > state.limits.max_object_children:
            state.mark_truncated()
            keys = keys[:state.limits.max_object_children]
        for key in keys:
            child = state.create_child(node, str(key))
            if child is None:
                continue
            _observe_value(value[key], child, depth=depth + 1, state=state)
        return

    if kind == JSONNodeKind.ARRAY:
        node.array_observations += 1
        size = len(value)
        node.array_min_items = size if node.array_min_items is None else min(node.array_min_items, size)
        node.array_max_items = size if node.array_max_items is None else max(node.array_max_items, size)
        sample = value[:state.limits.max_array_items]
        if len(value) > state.limits.max_array_items:
            state.mark_truncated()
        node.sampled_items += len(sample)
        if not sample:
            return
        child = state.create_child(node, JSON_ARRAY_ITEM_TOKEN)
        if child is None:
            return
        for item in sample:
            _observe_value(item, child, depth=depth + 1, state=state)


def _kind_from_value(value: Any) -> JSONNodeKind:
    if value is None:
        return JSONNodeKind.NULL
    if isinstance(value, bool):
        return JSONNodeKind.BOOLEAN
    if isinstance(value, int):
        return JSONNodeKind.INTEGER
    if isinstance(value, float):
        return JSONNodeKind.NUMBER
    if isinstance(value, str):
        return JSONNodeKind.STRING
    if isinstance(value, dict):
        return JSONNodeKind.OBJECT
    if isinstance(value, list):
        return JSONNodeKind.ARRAY
    return JSONNodeKind.UNKNOWN


def _build_structure_node(node: _ObservedNode, *, required: bool) -> JSONStructureNode:
    non_null_kinds = sorted(
        {kind for kind in node.observed_kinds if kind != JSONNodeKind.NULL},
        key=lambda kind: kind.value,
    )
    nullable = node.null_occurrences > 0

    if not non_null_kinds:
        kind = JSONNodeKind.NULL
    elif len(non_null_kinds) == 1:
        kind = non_null_kinds[0]
    else:
        kind = JSONNodeKind.UNION

    children: list[JSONStructureNode] = []
    object_keys: list[str] = []
    item_kind: JSONNodeKind | None = None
    array_min_items = None
    array_max_items = None
    sampled_items = None
    examples: list[Any] = []

    if kind == JSONNodeKind.OBJECT:
        object_keys = sorted(token for token in node.children if token != JSON_ARRAY_ITEM_TOKEN)
        for key in object_keys:
            child = node.children[key]
            child_required = node.object_observations > 0 and child.occurrences == node.object_observations
            children.append(_build_structure_node(child, required=child_required))
    elif kind == JSONNodeKind.ARRAY:
        array_min_items = node.array_min_items
        array_max_items = node.array_max_items
        sampled_items = node.sampled_items
        item_child = node.children.get(JSON_ARRAY_ITEM_TOKEN)
        if item_child is not None:
            item_kind = _effective_kind(item_child)
            item_required = node.sampled_items > 0 and item_child.occurrences == node.sampled_items
            children.append(_build_structure_node(item_child, required=item_required))
        else:
            item_kind = JSONNodeKind.UNKNOWN
    elif kind in JSON_SCALAR_NODE_KINDS or kind == JSONNodeKind.UNION:
        examples = node.examples[:]

    return JSONStructureNode(
        name=node.name,
        path=build_machine_json_path(node.tokens),
        display_path=build_display_json_path(node.tokens),
        kind=kind,
        required=required,
        nullable=nullable or kind == JSONNodeKind.NULL,
        occurrences=node.occurrences,
        kinds=non_null_kinds if kind == JSONNodeKind.UNION else [],
        object_keys=object_keys,
        children=children,
        item_kind=item_kind,
        array_min_items=array_min_items,
        array_max_items=array_max_items,
        sampled_items=sampled_items,
        examples=examples,
    )


def _effective_kind(node: _ObservedNode) -> JSONNodeKind:
    non_null_kinds = {kind for kind in node.observed_kinds if kind != JSONNodeKind.NULL}
    if not non_null_kinds:
        return JSONNodeKind.NULL
    if len(non_null_kinds) == 1:
        return next(iter(non_null_kinds))
    return JSONNodeKind.UNION


def _build_structure_stats(root: JSONStructureNode) -> JSONStructureStats:
    stats = JSONStructureStats()
    stack: list[tuple[JSONStructureNode, int]] = [(root, 0)]

    while stack:
        node, depth = stack.pop()
        stats.total_nodes += 1
        stats.max_depth = max(stats.max_depth, depth)

        if node.kind == JSONNodeKind.OBJECT:
            stats.object_nodes += 1
        elif node.kind == JSONNodeKind.ARRAY:
            stats.array_nodes += 1
        elif node.kind == JSONNodeKind.UNION:
            stats.union_nodes += 1
        else:
            stats.scalar_nodes += 1

        for child in reversed(node.children):
            stack.append((child, depth + 1))

    return stats


def _build_flatten_candidates(root: JSONStructureNode) -> list[JSONFlattenCandidate]:
    candidates: list[JSONFlattenCandidate] = []
    seen: set[tuple[str, JSONFlattenCandidateKind]] = set()
    stack = [root]

    while stack:
        node = stack.pop()

        if node.kind == JSONNodeKind.ARRAY:
            explode_confidence = 0.85 if node.item_kind in {JSONNodeKind.OBJECT, JSONNodeKind.UNION} else 0.75
            _add_candidate(
                candidates,
                seen,
                node=node,
                kind=JSONFlattenCandidateKind.EXPLODE_PATH,
                confidence=explode_confidence,
                reason="Array can be expanded into multiple output rows.",
            )

            if node.item_kind == JSONNodeKind.OBJECT:
                record_confidence = 0.95 if node.path == "/" else 0.9
                _add_candidate(
                    candidates,
                    seen,
                    node=node,
                    kind=JSONFlattenCandidateKind.RECORD_PATH,
                    confidence=record_confidence,
                    reason="Array of objects can be used as a record source.",
                )

        elif node.kind in JSON_SCALAR_NODE_KINDS or (
            node.kind == JSONNodeKind.UNION and all(kind in JSON_SCALAR_NODE_KINDS for kind in node.kinds)
        ):
            _add_candidate(
                candidates,
                seen,
                node=node,
                kind=JSONFlattenCandidateKind.META_PATH,
                confidence=0.8,
                reason="Scalar leaf can be propagated as metadata into normalized records.",
            )

        stack.extend(reversed(node.children))

    return sorted(
        candidates,
        key=lambda candidate: (-candidate.confidence, candidate.display_path, candidate.kind.value),
    )


def _add_candidate(
    candidates: list[JSONFlattenCandidate],
    seen: set[tuple[str, JSONFlattenCandidateKind]],
    *,
    node: JSONStructureNode,
    kind: JSONFlattenCandidateKind,
    confidence: float,
    reason: str,
) -> None:
    candidate_key = (node.path, kind)
    if candidate_key in seen:
        return
    seen.add(candidate_key)
    candidates.append(
        JSONFlattenCandidate(
            path=node.path,
            display_path=node.display_path,
            kind=kind,
            node_kind=node.kind,
            confidence=confidence,
            reason=reason,
        )
    )


def _build_inferred_schema(root: JSONStructureNode) -> dict[str, Any]:
    schema = _schema_for_node(root)
    schema["path"] = root.path
    schema["displayPath"] = root.display_path
    return schema


def _schema_for_node(node: JSONStructureNode) -> dict[str, Any]:
    if node.kind == JSONNodeKind.OBJECT:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                child.name: _schema_for_node(child)
                for child in node.children
                if child.name != JSON_ARRAY_ITEM_TOKEN
            },
            "required": [
                child.name
                for child in node.children
                if child.name != JSON_ARRAY_ITEM_TOKEN and child.required
            ],
        }
        if node.nullable:
            schema["nullable"] = True
        return schema

    if node.kind == JSONNodeKind.ARRAY:
        item_schema = None
        if node.children:
            item_schema = _schema_for_node(node.children[0])
        else:
            item_schema = {"type": "unknown"}
        schema = {
            "type": "array",
            "items": item_schema,
        }
        if node.array_min_items is not None:
            schema["minItems"] = node.array_min_items
        if node.array_max_items is not None:
            schema["maxItems"] = node.array_max_items
        if node.nullable:
            schema["nullable"] = True
        return schema

    if node.kind == JSONNodeKind.UNION:
        schema = {
            "anyOf": [
                {"type": _schema_type_for_kind(kind)}
                for kind in node.kinds
            ]
        }
        if node.nullable:
            schema["nullable"] = True
        if node.examples:
            schema["examples"] = node.examples
        return schema

    schema = {"type": _schema_type_for_kind(node.kind)}
    if node.nullable and node.kind != JSONNodeKind.NULL:
        schema["nullable"] = True
    if node.examples:
        schema["examples"] = node.examples
    return schema


def _schema_type_for_kind(kind: JSONNodeKind) -> str:
    mapping = {
        JSONNodeKind.OBJECT: "object",
        JSONNodeKind.ARRAY: "array",
        JSONNodeKind.STRING: "string",
        JSONNodeKind.INTEGER: "integer",
        JSONNodeKind.NUMBER: "number",
        JSONNodeKind.BOOLEAN: "boolean",
        JSONNodeKind.NULL: "null",
        JSONNodeKind.UNKNOWN: "unknown",
        JSONNodeKind.UNION: "union",
    }
    return mapping[kind]
