from __future__ import annotations

from core.metadata.json_metadata import get_json_metadata
from core.metadata.json_structure import JSONStructureLimits, infer_json_structure
from core.types import JSONFlattenCandidateKind, JSONMetadata, JSONNodeKind


def _find_node_by_display_path(root, display_path: str):
    stack = [root]
    while stack:
        node = stack.pop()
        if node.display_path == display_path:
            return node
        stack.extend(reversed(node.children))
    raise AssertionError(f"Node with path '{display_path}' not found.")


def _candidate_paths(metadata: JSONMetadata, kind: JSONFlattenCandidateKind) -> set[str]:
    return {
        candidate.display_path
        for candidate in metadata.flatten_candidates
        if candidate.kind == kind
    }


def test_get_json_metadata_builds_structure_for_simple_object() -> None:
    payload = {
        "requestId": "req-1",
        "result": {
            "total": 2,
            "duration": 1.5,
        },
    }

    metadata = get_json_metadata(payload)

    assert metadata.response == payload
    assert metadata.root is not None
    assert metadata.root.kind == JSONNodeKind.OBJECT
    assert metadata.stats is not None
    assert metadata.stats.object_nodes >= 2
    assert metadata.structure_truncated is False

    request_id_node = _find_node_by_display_path(metadata.root, "$.requestId")
    assert request_id_node.kind == JSONNodeKind.STRING
    assert request_id_node.required is True
    assert request_id_node.examples == ["req-1"]

    assert "$.requestId" in _candidate_paths(metadata, JSONFlattenCandidateKind.META_PATH)
    assert "$.result.total" in _candidate_paths(metadata, JSONFlattenCandidateKind.META_PATH)


def test_get_json_metadata_marks_optional_nullable_and_union_fields() -> None:
    payload = {
        "items": [
            {"id": 1, "name": "Alice", "nickname": None, "score": 10},
            {"id": 2, "name": "Bob", "score": "high"},
        ]
    }

    metadata = get_json_metadata(payload)
    assert metadata.root is not None

    items_node = _find_node_by_display_path(metadata.root, "$.items")
    assert items_node.kind == JSONNodeKind.ARRAY
    assert items_node.item_kind == JSONNodeKind.OBJECT

    nickname_node = _find_node_by_display_path(metadata.root, "$.items[].nickname")
    assert nickname_node.kind == JSONNodeKind.NULL
    assert nickname_node.required is False
    assert nickname_node.nullable is True

    score_node = _find_node_by_display_path(metadata.root, "$.items[].score")
    assert score_node.kind == JSONNodeKind.UNION
    assert set(score_node.kinds) == {JSONNodeKind.INTEGER, JSONNodeKind.STRING}
    assert score_node.required is True
    assert score_node.nullable is False


def test_get_json_metadata_builds_record_and_explode_candidates_for_root_array() -> None:
    payload = [
        {"id": 1, "tags": ["a", "b"]},
        {"id": 2, "tags": ["c"]},
    ]

    metadata = get_json_metadata(payload)

    assert metadata.root is not None
    assert metadata.root.kind == JSONNodeKind.ARRAY
    assert metadata.root.display_path == "$"
    assert "$" in _candidate_paths(metadata, JSONFlattenCandidateKind.RECORD_PATH)
    assert "$[].tags" in _candidate_paths(metadata, JSONFlattenCandidateKind.EXPLODE_PATH)


def test_get_json_metadata_treats_header_matrix_as_array_of_objects() -> None:
    payload = [
        ["ID", "NAME"],
        [1, "Alice"],
        [2, "Bob"],
        [3, "Carol"],
    ]

    metadata = get_json_metadata(payload)
    assert metadata.root is not None

    assert metadata.root.kind == JSONNodeKind.ARRAY
    assert "$" in _candidate_paths(metadata, JSONFlattenCandidateKind.RECORD_PATH)

    item_node = _find_node_by_display_path(metadata.root, "$[]")
    assert item_node.kind == JSONNodeKind.OBJECT

    id_node = _find_node_by_display_path(metadata.root, "$[].ID")
    assert id_node.kind == JSONNodeKind.INTEGER
    assert id_node.required is True

    name_node = _find_node_by_display_path(metadata.root, "$[].NAME")
    assert name_node.kind == JSONNodeKind.STRING
    assert name_node.required is True


def test_get_json_metadata_generates_synthetic_columns_for_matrix_without_header() -> None:
    payload = {
        "items": [
            [10, "Alice"],
            [20, "Bob"],
            [30, "Carol"],
            [40, "Dan"],
        ]
    }

    metadata = get_json_metadata(payload)
    assert metadata.root is not None

    assert "$.items" in _candidate_paths(metadata, JSONFlattenCandidateKind.RECORD_PATH)

    item_node = _find_node_by_display_path(metadata.root, "$.items[]")
    assert item_node.kind == JSONNodeKind.OBJECT

    first_column = _find_node_by_display_path(metadata.root, "$.items[].column_1")
    second_column = _find_node_by_display_path(metadata.root, "$.items[].column_2")
    assert first_column.kind == JSONNodeKind.INTEGER
    assert second_column.kind == JSONNodeKind.STRING


def test_infer_json_structure_respects_limits_and_marks_truncation() -> None:
    payload = {
        "items": [
            {
                "id": 1,
                "profile": {
                    "name": "Alice",
                    "details": {"age": 30, "city": "NY"},
                },
                "extra": {"x": 1},
            },
            {
                "id": 2,
                "profile": {
                    "name": "Bob",
                    "details": {"age": 31, "city": "LA"},
                },
                "extra": {"x": 2},
            },
        ]
    }

    result = infer_json_structure(
        payload,
        limits=JSONStructureLimits(
            max_depth=2,
            max_object_children=2,
            max_array_items=1,
            max_total_nodes=5,
        ),
    )

    assert result.structure_truncated is True
    assert result.root is not None
    assert len(result.root.children) <= 2


def test_get_json_metadata_includes_schema_like_representation() -> None:
    payload = {
        "items": [
            {"id": 1, "score": 10},
            {"id": 2, "score": "high"},
        ]
    }

    metadata = get_json_metadata(payload)

    assert metadata.inferred_schema is not None
    items_schema = metadata.inferred_schema["properties"]["items"]
    assert items_schema["type"] == "array"
    assert items_schema["items"]["type"] == "object"
    assert items_schema["items"]["properties"]["score"]["anyOf"] == [
        {"type": "integer"},
        {"type": "string"},
    ]
