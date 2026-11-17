from __future__ import annotations

import pytest

from src.modules.project_transfer.domain.entities import (
    BundleFolder,
    ColumnAnnotationSnapshot,
    GraphEdgeSnapshot,
    GraphNodeSnapshot,
    GraphSnapshot,
    GraphSubgraphSnapshot,
    ProjectFile,
)
from src.modules.project_transfer.domain.exceptions import (
    FolderDepthExceededError,
    InvalidBundleError,
    SecretsPassphraseRequiredError,
    WeakPassphraseError,
)
from src.modules.project_transfer.domain.policies import (
    apply_connection_ids,
    collect_connection_inputs,
    ensure_folder_depth_fits,
    order_folders,
    rebase_project_files,
    remap_graph_snapshot,
    resolve_variables,
    validate_passphrase,
)
from src.modules.project_transfer.domain.types import ConflictDecision
from src.modules.project_transfer.domain.value_objects import ConnectionBinding, VariableDecision


def _const(value):
    return {"__dvt_type": "const", "value": value}


def _graph() -> GraphSnapshot:
    return GraphSnapshot(
        subgraphs=[
            GraphSubgraphSnapshot(
                ui_id="sub-1", type="subgraph", position_x=0, position_y=0, name="S", display_name="S"
            )
        ],
        nodes=[
            GraphNodeSnapshot(
                ui_id="n-conn",
                type="custom",
                position_x=0,
                position_y=0,
                name="GetExistDBConnection",
                display_name="DB",
                input_values={"connection_id": _const("conn-src")},
                subgraph_id="sub-1",
            ),
            GraphNodeSnapshot(
                ui_id="n-file",
                type="custom",
                position_x=1,
                position_y=1,
                name="LoadCSV",
                display_name="CSV",
                input_values={
                    "connection": _const(
                        {
                            "id": "dvt-service-files:old:n-file:file",
                            "type": "dvt_service_files",
                            "properties": {
                                "organization_id": "old-org",
                                "project_id": "old-project",
                                "root_prefix": "node-inputs/n-file/file",
                            },
                        }
                    ),
                    "path": _const("data.csv"),
                },
            ),
        ],
        edges=[
            GraphEdgeSnapshot(
                ui_id="e-1", type="default", source="n-conn", target="n-file", subgraph_id="sub-1"
            )
        ],
        column_annotations=[
            ColumnAnnotationSnapshot(
                node_ui_id="n-file", port="output", column="amount", description="Сумма", origin_key="ds:d:f"
            ),
            ColumnAnnotationSnapshot(node_ui_id="ghost", port="output", column="x", description="Нет ноды"),
        ],
    )


def test_remap_moves_column_annotations_with_their_nodes_and_drops_dangling_ones():
    result = remap_graph_snapshot(_graph(), organization_id="org", project_id="new-project")

    assert len(result.snapshot.column_annotations) == 1
    annotation = result.snapshot.column_annotations[0]
    assert annotation.node_ui_id == result.mapping.nodes["n-file"]
    assert (annotation.port, annotation.column, annotation.description) == ("output", "amount", "Сумма")
    assert annotation.origin_key is None, "origin refers to ids of the source project"

    bindings = [ConnectionBinding(node_ui_id="n-conn", input_name="connection_id", connection_ref="connection-1")]
    with_connections = apply_connection_ids(
        result.snapshot, bindings, {"connection-1": "conn"}, node_ui_id_mapping=result.mapping.nodes
    )
    assert with_connections.column_annotations == result.snapshot.column_annotations


def test_remap_relinks_edges_subgraphs_and_service_files():
    result = remap_graph_snapshot(_graph(), organization_id="org", project_id="new-project")

    nodes = {node.ui_id: node for node in result.snapshot.nodes}
    assert set(nodes) == set(result.mapping.nodes.values())
    assert all(ui_id not in {"n-conn", "n-file"} for ui_id in nodes)

    edge = result.snapshot.edges[0]
    assert edge.source == result.mapping.nodes["n-conn"]
    assert edge.target == result.mapping.nodes["n-file"]
    assert edge.subgraph_id == result.mapping.subgraphs["sub-1"]
    assert nodes[result.mapping.nodes["n-conn"]].subgraph_id == result.mapping.subgraphs["sub-1"]

    new_file_node = result.mapping.nodes["n-file"]
    connection = nodes[new_file_node].input_values["connection"]["value"]
    assert connection["properties"] == {
        "organization_id": "org",
        "project_id": "new-project",
        "root_prefix": f"node-inputs/{new_file_node}/file",
    }
    assert connection["id"] == f"dvt-service-files:new-project:{new_file_node}:file"
    assert len(result.service_files_rewrites) == 1
    assert result.service_files_rewrites[0].old_root_prefix == "node-inputs/n-file/file"


def test_rebase_project_files_moves_only_files_under_rewritten_prefixes():
    result = remap_graph_snapshot(_graph(), organization_id="org", project_id="p")
    files = [
        ProjectFile(storage_path="node-inputs/n-file/file/data.csv", content=b"x"),
        ProjectFile(storage_path="node-inputs/n-file/file", is_dir=True),
        ProjectFile(storage_path="node-inputs/other/file/junk.csv", content=b"y"),
    ]

    rebased = rebase_project_files(files, result.service_files_rewrites)

    new_prefix = result.service_files_rewrites[0].new_root_prefix
    assert sorted(file.storage_path for file in rebased) == sorted([new_prefix, f"{new_prefix}/data.csv"])


def test_collect_connection_inputs_uses_definition_or_fallback():
    graph = _graph()
    graph.nodes.append(
        GraphNodeSnapshot(
            ui_id="n-unknown",
            type="custom",
            position_x=0,
            position_y=0,
            name="SomeExtensionNode",
            display_name="X",
            input_values={"connection_id": "plain-id", "other": _const("ignored")},
        )
    )

    found = collect_connection_inputs(graph, {"GetExistDBConnection": ("connection_id",), "LoadCSV": ()})

    assert found == [("n-conn", "connection_id", "conn-src"), ("n-unknown", "connection_id", "plain-id")]


def test_apply_connection_ids_writes_resolved_ids_after_remap():
    remapped = remap_graph_snapshot(_graph(), organization_id="org", project_id="p")
    bindings = [ConnectionBinding(node_ui_id="n-conn", input_name="connection_id", connection_ref="connection-1")]

    snapshot = apply_connection_ids(
        remapped.snapshot,
        bindings,
        {"connection-1": "conn-target"},
        node_ui_id_mapping=remapped.mapping.nodes,
    )

    node = next(node for node in snapshot.nodes if node.name == "GetExistDBConnection")
    assert node.input_values["connection_id"] == _const("conn-target")
    untouched = next(node for node in remapped.snapshot.nodes if node.name == "GetExistDBConnection")
    assert untouched.input_values["connection_id"] == _const("conn-src")


def test_apply_connection_ids_leaves_unresolved_refs_untouched():
    graph = _graph()
    bindings = [ConnectionBinding(node_ui_id="n-conn", input_name="connection_id", connection_ref="connection-1")]

    assert apply_connection_ids(graph, bindings, {}) is graph


def test_order_folders_is_parent_first_and_detects_cycles():
    folders = [
        BundleFolder(ref="c", name="C", parent_ref="b"),
        BundleFolder(ref="a", name="A"),
        BundleFolder(ref="b", name="B", parent_ref="a"),
    ]

    ordered = order_folders(folders)

    assert [(folder.ref, depth) for folder, depth in ordered] == [("a", 1), ("b", 2), ("c", 3)]
    with pytest.raises(InvalidBundleError):
        order_folders([BundleFolder(ref="x", name="X", parent_ref="y"), BundleFolder(ref="y", name="Y", parent_ref="x")])
    with pytest.raises(InvalidBundleError):
        order_folders([BundleFolder(ref="x", name="X", parent_ref="missing")])


def test_ensure_folder_depth_fits_respects_target_depth():
    folders = [BundleFolder(ref="a", name="A"), BundleFolder(ref="b", name="B", parent_ref="a")]

    ensure_folder_depth_fits(folders, target_depth=3, max_depth=5)
    with pytest.raises(FolderDepthExceededError):
        ensure_folder_depth_fits(folders, target_depth=4, max_depth=5)


def test_resolve_variables_honors_conflict_decisions_and_overrides():
    existing = {"a": {"type": "str", "value": "old", "is_list_type": False}}
    incoming = {
        "a": {"type": "str", "value": "new", "is_list_type": False},
        "b": {"type": "int", "value": 1, "is_list_type": False},
    }
    decisions = {
        "b": VariableDecision(value={"type": "int", "value": 42, "is_list_type": False}),
        "c": VariableDecision(value={"type": "str", "value": "added", "is_list_type": False}),
    }

    merged, kept = resolve_variables(existing, incoming, decisions)

    assert kept == ["a"]
    assert merged["a"]["value"] == "old"
    assert merged["b"]["value"] == 42
    assert merged["c"]["value"] == "added"

    merged, kept = resolve_variables(existing, incoming, {"a": VariableDecision(conflict=ConflictDecision.OVERWRITE)})
    assert kept == []
    assert merged["a"]["value"] == "new"


def test_validate_passphrase():
    assert validate_passphrase("longenough") == "longenough"
    with pytest.raises(SecretsPassphraseRequiredError):
        validate_passphrase(None)
    with pytest.raises(WeakPassphraseError):
        validate_passphrase("short")
