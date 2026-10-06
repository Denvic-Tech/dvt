"""The shared validate/apply preparation; no writes and no permanent ID allocation."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.routes.project.graph.graph_operations import GraphOperationsAggregated

from src.modules.project.infra.db_models import ProjectRecord

from ..auth import MCPPrincipal
from ..context import _available_definitions
from .arrangement import arrange_graph
from .connection_validation import existing_service_references
from .diagnostics import Diagnostic, Diagnostics
from .operations import build_operations, patch_preview
from .patching import apply_patch_to_state
from .references import ResolvedPatch, resolve_patch
from .schemas import GraphPatchSchema
from .state import GraphSnapshot
from .validation import validate_prepared_graph


@dataclass(frozen=True)
class PreparedPatch:
    payload: GraphOperationsAggregated
    references: ResolvedPatch
    warnings: list[Diagnostic]
    preview: dict[str, Any]


async def prepare_patch(
    *,
    snapshot: GraphSnapshot,
    session: AsyncSession,
    principal: MCPPrincipal,
    project: ProjectRecord,
    patch: GraphPatchSchema,
) -> PreparedPatch:
    graph = snapshot.state.working_copy()
    references = resolve_patch(patch, set(graph.nodes), set(graph.edges))
    service_references = existing_service_references(snapshot.state, project.id)
    diagnostics = Diagnostics()
    changes = apply_patch_to_state(graph, references, diagnostics)
    diagnostics.raise_if_invalid(references)

    arrangement = arrange_graph(graph, before=snapshot.state)
    for node_id, position in arrangement.positions.nodes.items():
        graph.nodes[node_id].position = position

    definitions = await _available_definitions(session, "en")
    diagnostics = await validate_prepared_graph(
        graph,
        changes,
        definitions=definitions,
        project=project,
        principal=principal,
        existing_references=service_references,
    )
    diagnostics.raise_if_invalid(references)
    payload = build_operations(graph, changes, arrangement.positions)
    return PreparedPatch(
        payload=payload,
        references=references,
        warnings=references.diagnostics(diagnostics.warnings),
        preview=patch_preview(payload, references, arrangement.positions, arrangement.bounds),
    )
