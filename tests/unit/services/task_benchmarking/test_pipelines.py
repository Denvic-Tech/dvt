"""Static consistency of the shipped benchmark scenarios against the registered node definitions.

``--validate-only`` and ``--dry-run`` do not instantiate nodes, so stale node names, input names
or links would otherwise surface only when a benchmark runs against a database.
"""

from pathlib import Path

import pytest
import yaml

from services.task_benchmarking.matrix import load_matrix_cases
from services.task_benchmarking.nodes import register_benchmark_nodes
from services.task_benchmarking.utils import load_pipeline

from src.node_dsl import _init_nodes, registry
from src.node_dsl.registry import nodes as nodes_registry

import config

PIPELINES_DIR = Path(__file__).resolve().parents[4] / "services" / "task_benchmarking" / "pipelines"
REPO_ROOT = PIPELINES_DIR.parents[2]
PIPELINE_FILES = sorted(PIPELINES_DIR.rglob("*.json"))
MATRIX_FILES = sorted(PIPELINES_DIR.rglob("*.yaml"))


def _iter_links(value):
    items = value if isinstance(value, list) else [value]
    for item in items:
        if isinstance(item, dict) and item.get("__dvt_type") == "link":
            yield item


@pytest.fixture(scope="module")
def registry_with_experimental_nodes():
    """Built-in registry rebuilt with EXPERIMENTAL nodes (as under DEBUG) plus benchmark nodes.

    Transform scenarios use experimental nodes such as DataFrameSortValues and DataFrameQuery,
    which the registry includes only when DEBUG is on (the compose ``.env`` sets it).
    """
    nodes_registry.get_all()
    snapshot = _init_nodes._snapshot_registries()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(config.DEBUG, "DEBUG", True)
        try:
            _init_nodes.init_nodes()
            register_benchmark_nodes()
            yield
        finally:
            _init_nodes._restore_registries(snapshot, restore_bootstrap_state=True)


@pytest.mark.parametrize("path", PIPELINE_FILES, ids=lambda path: path.name)
def test_pipeline_references_registered_nodes_inputs_and_outputs(
    registry_with_experimental_nodes, path
) -> None:
    pipeline = load_pipeline(str(path), pipeline_format="internal")

    for node_id, node in pipeline.items():
        definition = registry.get_definition(node["name"])
        unknown_inputs = set(node["inputs"]) - set(definition.input_definitions)
        assert not unknown_inputs, f"{node_id}: unknown inputs {sorted(unknown_inputs)}"
        for input_name, value in node["inputs"].items():
            if isinstance(value, dict) and value.get("__dvt_type") == "const":
                inner = value["value"]
                assert not (isinstance(inner, dict) and set(inner) == {"value"}), (
                    f"{node_id}.{input_name}: double-wrapped const"
                )
            for link in _iter_links(value):
                source = pipeline[link["node_id"]]
                source_outputs = registry.get_definition(source["name"]).output_definitions
                assert link["output_name"] in source_outputs, f"{node_id}.{input_name}: bad link"


@pytest.mark.parametrize("path", MATRIX_FILES, ids=lambda path: path.name)
def test_matrix_node_overrides_target_existing_const_inputs(path, monkeypatch) -> None:
    monkeypatch.chdir(REPO_ROOT)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = load_matrix_cases(
        matrix_path=str(path),
        default_pipeline=payload["pipelines"][0]["path"],
        default_pipeline_format="auto",
    )

    assert cases
    for case in cases:
        pipeline = load_pipeline(case.pipeline.path)
        for node_id, inputs in case.node_overrides.items():
            for input_name in inputs:
                # apply_input_overrides silently skips inputs that are absent from the JSON.
                assert input_name in pipeline[node_id]["inputs"], f"{case.name}: {input_name}"
