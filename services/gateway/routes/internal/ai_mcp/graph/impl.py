"""MCP graph entrypoints: access, version, preparation, persistence, response."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.gateway.routes.project.graph.graph_operations import ApplyGraphOperationsUseCase

from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.domain.types import TaskSource

from ..access import get_accessible_project
from ..auth import MCPPrincipal
from .arrangement import arrange_graph
from .operations import position_operations
from .preparation import prepare_patch
from .reading import graph_page
from .schemas import GraphPatchSchema
from .snapshot import check_graph_version, load_snapshot
from .state import GraphSnapshot


async def _checked_snapshot(
    session: AsyncSession,
    principal: MCPPrincipal,
    project_id: str,
    *,
    revision: int,
    etag: str,
    for_update: bool = False,
) -> tuple[ProjectRecord, GraphSnapshot]:
    project = await get_accessible_project(session, principal, project_id, for_update=for_update)
    snapshot = await load_snapshot(session, project)
    check_graph_version(project, snapshot, revision, etag)
    return project, snapshot


async def get_project_graph(
    *,
    session: AsyncSession,
    principal: MCPPrincipal,
    project_id: str,
    cursor: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    project = await get_accessible_project(session, principal, project_id)
    snapshot = await load_snapshot(session, project)
    return await graph_page(
        snapshot,
        project_id=project.id,
        revision=project.graph_revision,
        principal=principal,
        cursor=cursor,
        limit=limit,
    )


async def validate_graph_changes(
    *,
    session: AsyncSession,
    principal: MCPPrincipal,
    project_id: str,
    expected_graph_revision: int,
    expected_graph_etag: str,
    patch: dict[str, Any] | GraphPatchSchema,
) -> dict[str, Any]:
    project, snapshot = await _checked_snapshot(
        session,
        principal,
        project_id,
        revision=expected_graph_revision,
        etag=expected_graph_etag,
    )
    prepared = await prepare_patch(
        snapshot=snapshot,
        session=session,
        principal=principal,
        project=project,
        patch=GraphPatchSchema.model_validate(patch),
    )
    return {"valid": True, "warnings": prepared.warnings, "preview": prepared.preview}


async def apply_graph_changes(
    *,
    session: AsyncSession,
    principal: MCPPrincipal,
    project_id: str,
    expected_graph_revision: int,
    expected_graph_etag: str,
    patch: dict[str, Any] | GraphPatchSchema,
) -> dict[str, Any]:
    project, snapshot = await _checked_snapshot(
        session,
        principal,
        project_id,
        revision=expected_graph_revision,
        etag=expected_graph_etag,
        for_update=True,
    )
    prepared = await prepare_patch(
        snapshot=snapshot,
        session=session,
        principal=principal,
        project=project,
        patch=GraphPatchSchema.model_validate(patch),
    )
    node_ids_by_ref = prepared.references.materialize(prepared.payload)
    result = await ApplyGraphOperationsUseCase().execute(
        project_id=project_id,
        payload=prepared.payload,
        user=principal.user,
        session=session,
        source=TaskSource.MCP,
    )
    refreshed = await get_accessible_project(session, principal, project_id)
    saved = await load_snapshot(session, refreshed, populate_existing=True)
    return {
        **result.model_dump(mode="json"),
        "graph_revision": refreshed.graph_revision,
        "graph_etag": saved.etag,
        "warnings": prepared.warnings,
        "node_ids_by_ref": node_ids_by_ref,
    }


async def auto_layout_project(
    *,
    session: AsyncSession,
    principal: MCPPrincipal,
    project_id: str,
    expected_graph_revision: int,
    expected_graph_etag: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    project, snapshot = await _checked_snapshot(
        session,
        principal,
        project_id,
        revision=expected_graph_revision,
        etag=expected_graph_etag,
        for_update=not dry_run,
    )
    arrangement = arrange_graph(snapshot.state, full=True)
    positions = arrangement.positions
    etag = snapshot.etag
    if not dry_run and positions.count:
        await ApplyGraphOperationsUseCase().execute(
            project_id=project_id,
            payload=position_operations(positions),
            user=principal.user,
            session=session,
            source=TaskSource.MCP,
        )
        saved = await load_snapshot(session, project, populate_existing=True)
        etag = saved.etag
    return {
        "dry_run": dry_run,
        "moved_node_ids": sorted(positions.nodes),
        "moved_subgraph_ids": sorted(positions.subgraphs),
        "changes_count": positions.count,
        "bounds": arrangement.bounds.mapping(),
        "graph_revision": project.graph_revision,
        "graph_etag": etag,
    }
