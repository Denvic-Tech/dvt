from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from core.types import JSONMetadata, JSONNodeKind
from src.nodes.json.json_editor import JSONEditor


def _run_node(payload, **kwargs):
    node = JSONEditor(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-json-editor",
        json=payload,
        **kwargs,
    )
    node.process()
    return node


def test_json_editor_supports_explicit_record_meta_explode_keep_and_exclude_paths() -> None:
    payload = {
        "requestId": "req-1",
        "result": {
            "total": 2,
            "items": [
                {
                    "id": 1,
                    "name": "Alice",
                    "contacts": [
                        {"type": "email", "value": "alice@example.com"},
                        {"type": "phone", "value": "123"},
                    ],
                    "profile": {"age": 30, "skills": ["python", "sql"]},
                    "internal": {"secret": True},
                },
                {
                    "id": 2,
                    "name": "Bob",
                    "contacts": [],
                    "profile": {"age": 25, "skills": ["excel"]},
                    "internal": {"secret": False},
                },
            ],
        },
    }

    node = _run_node(
        payload,
        record_path="$.result.items",
        meta_paths=["$.requestId", "$.result.total", "missing"],
        explode_paths=["contacts"],
        keep_json_paths=["profile"],
        exclude_paths=["internal"],
    )

    assert node.output == [
        {
            "id": 1,
            "name": "Alice",
            "contacts.type": "email",
            "contacts.value": "alice@example.com",
            "profile": {"age": 30, "skills": ["python", "sql"]},
            "requestId": "req-1",
            "result.total": 2,
            "missing": None,
        },
        {
            "id": 1,
            "name": "Alice",
            "contacts.type": "phone",
            "contacts.value": "123",
            "profile": {"age": 30, "skills": ["python", "sql"]},
            "requestId": "req-1",
            "result.total": 2,
            "missing": None,
        },
        {
            "id": 2,
            "name": "Bob",
            "contacts": None,
            "profile": {"age": 25, "skills": ["excel"]},
            "requestId": "req-1",
            "result.total": 2,
            "missing": None,
        },
    ]


def test_json_editor_auto_detects_record_path_from_metadata() -> None:
    payload = {
        "meta": {"source": "api"},
        "items": [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ],
    }

    node = _run_node(
        payload,
        auto_detect_record_path=True,
        meta_paths=["$.meta.source"],
    )

    assert node.stats["effective_record_path"] == "$.items"
    assert node.output == [
        {"id": 1, "name": "Alice", "meta.source": "api"},
        {"id": 2, "name": "Bob", "meta.source": "api"},
    ]


def test_json_editor_uses_root_array_as_record_source() -> None:
    payload = [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
    ]

    node = _run_node(payload, auto_detect_record_path=False)

    assert node.stats["effective_record_path"] == "$"
    assert node.output == [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
    ]


def test_json_editor_normalizes_matrix_header_rows_into_records() -> None:
    payload = [
        ["ID", "NAME", "NAME", ""],
        [1, "Alice", "A", "x"],
        [2, "Bob"],
        [3, "Carol", "C", "y"],
        [4, "Dan", "D", "z"],
    ]

    node = _run_node(payload)

    assert node.output == [
        {"ID": 1, "NAME": "Alice", "NAME__2": "A", "column_4": "x"},
        {"ID": 2, "NAME": "Bob", "NAME__2": None, "column_4": None},
        {"ID": 3, "NAME": "Carol", "NAME__2": "C", "column_4": "y"},
        {"ID": 4, "NAME": "Dan", "NAME__2": "D", "column_4": "z"},
    ]
    assert node.stats["effective_record_path"] == "$"
    assert node.stats["detected_matrix"] is True
    assert node.stats["matrix_header_mode"] == "header_row"
    assert node.stats["matrix_columns"] == ["ID", "NAME", "NAME__2", "column_4"]
    assert any("NAME -> NAME__2" in warning for warning in node.stats["warnings"])
    assert any("Padded short matrix rows" in warning for warning in node.stats["warnings"])


def test_json_editor_generates_synthetic_columns_for_matrix_without_header() -> None:
    payload = {
        "items": [
            [100, "Alice"],
            [200, "Bob", "extra"],
            [300, "Carol"],
            [400, "Dan"],
            [500, "Eve"],
        ]
    }

    node = _run_node(payload, record_path="$.items")

    assert node.output == [
        {"column_1": 100, "column_2": "Alice"},
        {"column_1": 200, "column_2": "Bob", "_extra_values": ["extra"]},
        {"column_1": 300, "column_2": "Carol"},
        {"column_1": 400, "column_2": "Dan"},
        {"column_1": 500, "column_2": "Eve"},
    ]
    assert node.stats["detected_matrix"] is True
    assert node.stats["matrix_header_mode"] == "synthetic"
    assert node.stats["matrix_columns"] == ["column_1", "column_2"]
    assert any("Generated synthetic matrix columns" in warning for warning in node.stats["warnings"])
    assert any("_extra_values" in warning for warning in node.stats["warnings"])


def test_json_editor_supports_object_record_path_and_exclude_overrides_other_rules() -> None:
    payload = {
        "result": {
            "item": {
                "id": 1,
                "tags": ["a", "b"],
                "profile": {"level": 2},
                "secret": {"token": "x"},
            }
        }
    }

    node = _run_node(
        payload,
        record_path="$.result.item",
        explode_paths=["tags", "secret"],
        keep_json_paths=["profile", "secret"],
        exclude_paths=["secret"],
    )

    assert node.output == [
        {"id": 1, "tags": "a", "profile": {"level": 2}},
        {"id": 1, "tags": "b", "profile": {"level": 2}},
    ]


def test_json_editor_limits_rows_deterministically() -> None:
    payload = {
        "items": [
            {"id": 1, "tags": [1, 2, 3]},
            {"id": 2, "tags": [4, 5, 6]},
        ]
    }

    node = _run_node(
        payload,
        record_path="$.items",
        explode_paths=["tags"],
        max_rows=4,
    )

    assert node.output == [
        {"id": 1, "tags": 1},
        {"id": 1, "tags": 2},
        {"id": 1, "tags": 3},
        {"id": 2, "tags": 4},
    ]
    assert node.stats["rows_truncated"] is True


def test_json_editor_handles_missing_record_path_and_nested_arrays() -> None:
    missing_record_node = _run_node(
        {"items": [{"id": 1}]},
        record_path="$.missing.records",
    )
    assert missing_record_node.output == []

    nested_arrays_node = _run_node(
        {"items": [{"id": 1, "groups": [["a", "b"], ["c"]]}]},
        record_path="$.items",
        explode_paths=["groups"],
    )
    assert nested_arrays_node.output == [
        {"id": 1, "groups": ["a", "b"]},
        {"id": 1, "groups": ["c"]},
    ]


def test_json_editor_converts_special_values_to_json_safe_output() -> None:
    payload = {
        "items": [
            {
                "dt": datetime(2024, 1, 2, 3, 4, 5),
                "stamp": pd.Timestamp("2024-02-03T04:05:06Z"),
                "amount": Decimal("12.5"),
                "values": np.array([1, 2]),
                "labels": {"x", "y"},
                "nan": float("nan"),
                "inf": float("inf"),
            }
        ]
    }

    node = _run_node(payload, record_path="$.items")

    assert node.output == [
        {
            "dt": "2024-01-02T03:04:05",
            "stamp": "2024-02-03T04:05:06+00:00",
            "amount": 12.5,
            "values": [1, 2],
            "labels": ["x", "y"],
            "nan": None,
            "inf": None,
        }
    ]


@pytest.mark.asyncio
async def test_json_editor_resolve_metadata_returns_structured_json_metadata() -> None:
    node = _run_node(
        {"items": [{"id": 1}, {"id": 2}]},
        record_path="$.items",
    )

    metadata = await node.resolve_metadata()

    assert "output" in metadata
    assert isinstance(metadata["output"], JSONMetadata)
    assert metadata["output"].root is not None
    assert metadata["output"].root.kind == JSONNodeKind.ARRAY
