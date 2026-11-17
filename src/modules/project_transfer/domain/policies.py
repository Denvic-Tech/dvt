from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from typing import Any
from uuid import uuid4

from .entities import (
    BundleFolder,
    GraphIdMapping,
    GraphRemapResult,
    GraphSnapshot,
    ProjectFile,
    ServiceFilesPrefixRewrite,
)
from .exceptions import (
    FolderDepthExceededError,
    InvalidBundleError,
    SecretsPassphraseRequiredError,
    WeakPassphraseError,
)
from .types import ConflictDecision
from .value_objects import ConnectionBinding, VariableDecision

SERVICE_FILES_CONNECTION_TYPE = "dvt_service_files"
SERVICE_FILES_NODE_INPUTS_ROOT = "node-inputs"
CONST_INPUT_MARKER = "const"
INPUT_TYPE_MARKER = "__dvt_type"
FALLBACK_CONNECTION_INPUT_NAME = "connection_id"
MIN_PASSPHRASE_LENGTH = 8
PROJECT_FOLDER_MAX_DEPTH = 5


def new_node_ui_id() -> str:
    return f"node_{uuid4()}"


def new_subgraph_ui_id() -> str:
    return f"subgraph_{uuid4()}"


def new_edge_ui_id() -> str:
    return f"edge_{uuid4()}"


# --- Node-attached file connections ------------------------------------------


def is_service_files_connection(value: object) -> bool:
    return isinstance(value, dict) and value.get("type") == SERVICE_FILES_CONNECTION_TYPE


def extract_service_files_connection(input_values: object) -> dict[str, Any] | None:
    """Return the embedded node-file-input connection of a node, if any."""
    if not isinstance(input_values, dict):
        return None
    connection_input = input_values.get("connection")
    if not isinstance(connection_input, dict):
        return None
    if connection_input.get(INPUT_TYPE_MARKER) != CONST_INPUT_MARKER:
        return None
    connection = connection_input.get("value")
    if not is_service_files_connection(connection):
        return None
    return connection


def service_files_root_prefix(node_ui_id: str, input_name: str) -> str:
    return f"{SERVICE_FILES_NODE_INPUTS_ROOT}/{node_ui_id}/{input_name}"


def service_files_connection_id(project_id: str, node_ui_id: str, input_name: str) -> str:
    return f"{SERVICE_FILES_CONNECTION_TYPE.replace('_', '-')}:{project_id}:{node_ui_id}:{input_name}"


def _rebase_root_prefix(old_root_prefix: str, *, node_ui_id: str) -> str:
    parts = [part for part in old_root_prefix.strip("/").split("/") if part]
    if len(parts) >= 3 and parts[0] == SERVICE_FILES_NODE_INPUTS_ROOT:
        return "/".join([SERVICE_FILES_NODE_INPUTS_ROOT, node_ui_id, *parts[2:]])
    return service_files_root_prefix(node_ui_id, "file")


def rewrite_service_files_input_values(
    input_values: Any,
    *,
    organization_id: str,
    project_id: str,
    node_ui_id: str,
) -> tuple[Any, ServiceFilesPrefixRewrite | None]:
    """Re-own an embedded node-file-input connection to a new project/node.

    Returns the rewritten input values and the storage prefix move that the
    caller must apply to the stored file objects.
    """
    connection = extract_service_files_connection(input_values)
    if connection is None:
        return input_values, None

    rewritten_input_values = deepcopy(input_values)
    rewritten_connection = rewritten_input_values["connection"]["value"]
    properties = dict(rewritten_connection.get("properties") or {})
    old_root_prefix = str(properties.get("root_prefix") or "").strip("/")
    new_root_prefix = _rebase_root_prefix(old_root_prefix, node_ui_id=node_ui_id)

    properties.update(
        {
            "organization_id": organization_id,
            "project_id": project_id,
            "root_prefix": new_root_prefix,
        }
    )
    rewritten_connection["id"] = service_files_connection_id(
        project_id,
        node_ui_id,
        new_root_prefix.rsplit("/", 1)[-1],
    )
    rewritten_connection["properties"] = properties
    return rewritten_input_values, ServiceFilesPrefixRewrite(
        old_root_prefix=old_root_prefix,
        new_root_prefix=new_root_prefix,
    )


def rebase_service_file_path(path: str, rewrite: ServiceFilesPrefixRewrite) -> str | None:
    """Map a stored file path to the new prefix; None when the path is outside the prefix."""
    if not rewrite.old_root_prefix:
        return None
    normalized = path.strip("/")
    if normalized == rewrite.old_root_prefix:
        return rewrite.new_root_prefix
    if normalized.startswith(f"{rewrite.old_root_prefix}/"):
        return f"{rewrite.new_root_prefix}{normalized[len(rewrite.old_root_prefix):]}"
    return None


def rebase_project_files(
    files: Iterable[ProjectFile],
    rewrites: Sequence[ServiceFilesPrefixRewrite],
) -> list[ProjectFile]:
    """Move bundled files under the prefixes of their remapped nodes.

    Files that belong to no rewritten prefix are dropped: nothing references them.
    """
    rebased: list[ProjectFile] = []
    seen_paths: set[str] = set()
    for file in files:
        for rewrite in rewrites:
            new_path = rebase_service_file_path(file.storage_path, rewrite)
            if new_path is None or new_path in seen_paths:
                continue
            seen_paths.add(new_path)
            rebased.append(replace(file, storage_path=new_path))
            break
    return rebased


# --- Graph remap ------------------------------------------------------------


def remap_graph_snapshot(
    snapshot: GraphSnapshot,
    *,
    organization_id: str,
    project_id: str,
    node_ui_id_factory: Callable[[], str] = new_node_ui_id,
    subgraph_ui_id_factory: Callable[[], str] = new_subgraph_ui_id,
    edge_ui_id_factory: Callable[[], str] = new_edge_ui_id,
) -> GraphRemapResult:
    """Assign fresh ui_ids to every graph element and relink references.

    Edges keep pointing at the same nodes, nodes and edges keep belonging to the
    same subgraphs, and node-attached file connections are re-owned to the
    target project. Dangling references are preserved as-is, except column
    annotations of unknown nodes, which are dropped: they cannot exist without
    their node. ``origin_key`` of an annotation refers to ids of the source
    project and is reset.
    """
    mapping = GraphIdMapping()

    remapped_subgraphs = []
    for subgraph in snapshot.subgraphs:
        new_ui_id = subgraph_ui_id_factory()
        mapping.subgraphs[subgraph.ui_id] = new_ui_id
        remapped_subgraphs.append(replace(subgraph, ui_id=new_ui_id))

    rewrites: list[ServiceFilesPrefixRewrite] = []
    remapped_nodes = []
    for node in snapshot.nodes:
        new_ui_id = node_ui_id_factory()
        mapping.nodes[node.ui_id] = new_ui_id
        input_values, rewrite = rewrite_service_files_input_values(
            node.input_values,
            organization_id=organization_id,
            project_id=project_id,
            node_ui_id=new_ui_id,
        )
        if rewrite is not None:
            rewrites.append(rewrite)
        remapped_nodes.append(
            replace(
                node,
                ui_id=new_ui_id,
                input_values=input_values,
                subgraph_id=mapping.subgraphs.get(node.subgraph_id, node.subgraph_id),
            )
        )

    remapped_edges = []
    for edge in snapshot.edges:
        new_ui_id = edge_ui_id_factory()
        mapping.edges[edge.ui_id] = new_ui_id
        remapped_edges.append(
            replace(
                edge,
                ui_id=new_ui_id,
                source=mapping.nodes.get(edge.source, edge.source),
                target=mapping.nodes.get(edge.target, edge.target),
                subgraph_id=mapping.subgraphs.get(edge.subgraph_id, edge.subgraph_id),
            )
        )

    remapped_annotations = [
        replace(annotation, node_ui_id=mapping.nodes[annotation.node_ui_id], origin_key=None)
        for annotation in snapshot.column_annotations
        if annotation.node_ui_id in mapping.nodes
    ]

    return GraphRemapResult(
        snapshot=GraphSnapshot(
            subgraphs=remapped_subgraphs,
            nodes=remapped_nodes,
            edges=remapped_edges,
            column_annotations=remapped_annotations,
        ),
        mapping=mapping,
        service_files_rewrites=rewrites,
    )


# --- Connection references in node inputs -------------------------------------


def read_const_string(input_values: Any, input_name: str) -> str | None:
    if not isinstance(input_values, dict):
        return None
    raw = input_values.get(input_name)
    if isinstance(raw, dict):
        if raw.get(INPUT_TYPE_MARKER) != CONST_INPUT_MARKER:
            return None
        raw = raw.get("value")
    return raw if isinstance(raw, str) and raw else None


def collect_connection_inputs(
    snapshot: GraphSnapshot,
    connection_inputs_by_node_name: Mapping[str, Sequence[str] | None],
) -> list[tuple[str, str, str]]:
    """``(node_ui_id, input_name, connection_id)`` for every node input holding a connection id.

    ``connection_inputs_by_node_name`` maps a node class name to its connection-id
    input names, or to None when the node is unknown on this instance; unknown
    nodes fall back to the conventional ``connection_id`` input.
    """
    found: list[tuple[str, str, str]] = []
    for node in snapshot.nodes:
        input_names = connection_inputs_by_node_name.get(node.name)
        if input_names is None:
            input_names = (FALLBACK_CONNECTION_INPUT_NAME,)
        for input_name in input_names:
            connection_id = read_const_string(node.input_values, input_name)
            if connection_id is not None:
                found.append((node.ui_id, input_name, connection_id))
    return found


def apply_connection_ids(
    snapshot: GraphSnapshot,
    bindings: Iterable[ConnectionBinding],
    connection_ids_by_ref: Mapping[str, str],
    *,
    node_ui_id_mapping: Mapping[str, str] | None = None,
) -> GraphSnapshot:
    """Write resolved connection ids into bound node inputs.

    Bindings whose ref has no resolved id are left untouched. ``node_ui_id_mapping``
    translates binding node ids when the snapshot was remapped before.
    """
    targets: dict[tuple[str, str], str] = {}
    for binding in bindings:
        connection_id = connection_ids_by_ref.get(binding.connection_ref)
        if connection_id is None:
            continue
        node_ui_id = binding.node_ui_id
        if node_ui_id_mapping is not None:
            node_ui_id = node_ui_id_mapping.get(node_ui_id, node_ui_id)
        targets[(node_ui_id, binding.input_name)] = connection_id
    if not targets:
        return snapshot

    nodes = []
    for node in snapshot.nodes:
        updated_values = None
        for (node_ui_id, input_name), connection_id in targets.items():
            if node_ui_id != node.ui_id:
                continue
            if updated_values is None:
                updated_values = deepcopy(node.input_values) if isinstance(node.input_values, dict) else {}
            updated_values[input_name] = {INPUT_TYPE_MARKER: CONST_INPUT_MARKER, "value": connection_id}
        nodes.append(node if updated_values is None else replace(node, input_values=updated_values))
    return replace(snapshot, nodes=nodes)


# --- Folders ----------------------------------------------------------------


def order_folders(folders: Sequence[BundleFolder]) -> list[tuple[BundleFolder, int]]:
    """Folders in parent-first order with their depth (root bundle folder = 1).

    Raises ``InvalidBundleError`` on duplicate refs, unknown parents or cycles.
    """
    by_ref: dict[str, BundleFolder] = {}
    for folder in folders:
        if folder.ref in by_ref:
            raise InvalidBundleError(f"Duplicate folder ref '{folder.ref}' in bundle")
        by_ref[folder.ref] = folder

    depths: dict[str, int] = {}

    def depth_of(ref: str, trail: tuple[str, ...]) -> int:
        if ref in depths:
            return depths[ref]
        if ref in trail:
            raise InvalidBundleError(f"Folder cycle in bundle: {' -> '.join((*trail, ref))}")
        folder = by_ref.get(ref)
        if folder is None:
            raise InvalidBundleError(f"Folder '{ref}' refers to unknown parent folder")
        depth = 1 if folder.parent_ref is None else depth_of(folder.parent_ref, (*trail, ref)) + 1
        depths[ref] = depth
        return depth

    for ref in by_ref:
        depth_of(ref, ())

    return sorted(((by_ref[ref], depths[ref]) for ref in by_ref), key=lambda item: (item[1], item[0].ref))


def ensure_folder_depth_fits(
    folders: Sequence[BundleFolder],
    *,
    target_depth: int,
    max_depth: int = PROJECT_FOLDER_MAX_DEPTH,
) -> None:
    """``target_depth`` is the depth of the folder the bundle is imported into (0 = root)."""
    bundle_depth = max((depth for _folder, depth in order_folders(folders)), default=0)
    if target_depth + bundle_depth > max_depth:
        raise FolderDepthExceededError(
            f"Bundle folders need depth {bundle_depth} under a folder at depth {target_depth}, "
            f"maximum is {max_depth}"
        )


# --- Variables --------------------------------------------------------------


def resolve_variables(
    existing: Mapping[str, dict[str, Any]] | None,
    incoming: Mapping[str, dict[str, Any]] | None,
    decisions: Mapping[str, VariableDecision] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Merge bundled variables into existing ones honoring per-key decisions.

    Returns the merged mapping and the keys that conflicted and were kept.
    A decision ``value`` overrides the bundled payload for that key.
    """
    merged: dict[str, dict[str, Any]] = {key: dict(value) for key, value in (existing or {}).items()}
    kept: list[str] = []
    decisions = decisions or {}
    for key, payload in (incoming or {}).items():
        decision = decisions.get(key)
        value = payload if decision is None or decision.value is None else decision.value
        if key in merged and (decision is None or decision.conflict != ConflictDecision.OVERWRITE):
            kept.append(key)
            continue
        merged[key] = dict(value)
    for key, decision in decisions.items():
        if key not in (incoming or {}) and decision.value is not None and key not in merged:
            merged[key] = dict(decision.value)
    return merged, kept


# --- Secrets ----------------------------------------------------------------


def validate_passphrase(passphrase: str | None) -> str:
    if not passphrase:
        raise SecretsPassphraseRequiredError()
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise WeakPassphraseError(
            f"Passphrase must be at least {MIN_PASSPHRASE_LENGTH} characters long"
        )
    return passphrase
