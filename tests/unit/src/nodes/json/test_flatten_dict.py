from src.nodes.json.flatten_dict import ExpandJSON


def _run_node(payload, **kwargs):
    node = ExpandJSON(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-expand-json",
        json=payload,
        **kwargs,
    )
    node.process()
    return node.output


def test_expand_json_flattens_nested_dicts_inside_exploded_arrays() -> None:
    payload = {
        "id": 1,
        "items": [
            {
                "name": "first",
                "meta": {
                    "code": "A1",
                    "details": {"value": 10},
                },
            },
            {
                "name": "second",
                "meta": {
                    "code": "B2",
                    "details": {"value": 20},
                },
            },
        ],
    }

    output = _run_node(payload)

    assert output == [
        {
            "id": 1,
            "items.meta.code": "A1",
            "items.meta.details.value": 10,
            "items.name": "first",
        },
        {
            "id": 1,
            "items.meta.code": "B2",
            "items.meta.details.value": 20,
            "items.name": "second",
        },
    ]


def test_expand_json_recursively_expands_nested_arrays_after_outer_explode() -> None:
    payload = {
        "items": [
            {
                "name": "first",
                "tags": [
                    {"label": "x"},
                    {"label": "y"},
                ],
            },
            {
                "name": "second",
                "tags": [{"label": "z"}],
            },
        ]
    }

    output = _run_node(payload)

    assert output == [
        {
            "items.name": "first",
            "items.tags.label": "x",
        },
        {
            "items.name": "first",
            "items.tags.label": "y",
        },
        {
            "items.name": "second",
            "items.tags.label": "z",
        },
    ]


def test_expand_json_preserves_arrays_when_cartesian_product_exceeds_limit() -> None:
    node = ExpandJSON(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-expand-json",
        json={
            "left": [
                {"id": 1, "label": "A"},
                {"id": 2, "label": "B"},
                {"id": 3, "label": "C"},
            ],
            "right": [
                {"id": 10, "label": "X"},
                {"id": 20, "label": "Y"},
                {"id": 30, "label": "Z"},
            ],
        },
        max_total_rows=5,
    )

    node.process()

    assert node.output == [
        {
            "left": [
                {"id": 1, "label": "A"},
                {"id": 2, "label": "B"},
                {"id": 3, "label": "C"},
            ],
            "right": [
                {"id": 10, "label": "X"},
                {"id": 20, "label": "Y"},
                {"id": 30, "label": "Z"},
            ],
        }
    ]
    assert any("массивы сохранены без размножения" in warning for warning in node.stats["warnings"])


def test_expand_json_applies_limit_before_nested_expansion_materialization() -> None:
    node = ExpandJSON(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-expand-json",
        json={
            "outer": [
                {
                    "name": f"row-{idx}",
                    "inner": [{"id": idx} for idx in range(10)],
                }
                for idx in range(3)
            ]
        },
        max_total_rows=25,
    )

    node.process()

    assert len(node.output) == 21
    assert node.output[-1]["outer.name"] == "row-2"
    assert node.output[-1]["outer.inner"] == [{"id": idx} for idx in range(10)]
    assert any("массивы сохранены без размножения" in warning for warning in node.stats["warnings"])
