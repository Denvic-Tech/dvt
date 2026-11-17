"""Persistence helpers for moving a project graph between projects.

Shared by project copy and project import. Pure remap rules live in
``domain.policies``; this module only reads and writes rows.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.data_catalog.infra.db_models import NodeColumnAnnotationRecord
from src.modules.file_storage.infra.db_models import DVTServiceFileObjectRecord
from src.modules.pipeline_graph.infra.db_models import (
    GraphEdgeRecord,
    GraphNodeRecord,
    SubgraphRecord,
)
from src.modules.project_transfer.domain.entities import (
    ColumnAnnotationSnapshot,
    GraphEdgeSnapshot,
    GraphNodeSnapshot,
    GraphSnapshot,
    GraphSubgraphSnapshot,
    ServiceFilesPrefixRewrite,
)
from src.modules.project_transfer.domain.policies import rebase_service_file_path


async def read_graph_snapshot(session: AsyncSession, project_id: str) -> GraphSnapshot:
    subgraph_rows = (
        await session.execute(
            sa.select(
                SubgraphRecord.ui_id,
                SubgraphRecord.type,
                SubgraphRecord.position_x,
                SubgraphRecord.position_y,
                SubgraphRecord.selected,
                SubgraphRecord.expanded,
                SubgraphRecord.name,
                SubgraphRecord.display_name,
                SubgraphRecord.comment,
                SubgraphRecord.color,
            )
            .where(SubgraphRecord.project_id == project_id)
            .order_by(SubgraphRecord.ui_id)
        )
    ).all()
    node_rows = (
        await session.execute(
            sa.select(
                GraphNodeRecord.ui_id,
                GraphNodeRecord.type,
                GraphNodeRecord.position_x,
                GraphNodeRecord.position_y,
                GraphNodeRecord.selected,
                GraphNodeRecord.name,
                GraphNodeRecord.display_name,
                GraphNodeRecord.comment,
                GraphNodeRecord.show_signal_io,
                GraphNodeRecord.show_variables_io,
                GraphNodeRecord.store_enabled,
                GraphNodeRecord.input_values,
                GraphNodeRecord.subgraph_id,
            )
            .where(GraphNodeRecord.project_id == project_id)
            .order_by(GraphNodeRecord.ui_id)
        )
    ).all()
    edge_rows = (
        await session.execute(
            sa.select(
                GraphEdgeRecord.ui_id,
                GraphEdgeRecord.type,
                GraphEdgeRecord.source,
                GraphEdgeRecord.source_handle,
                GraphEdgeRecord.target,
                GraphEdgeRecord.target_handle,
                GraphEdgeRecord.subgraph_id,
            )
            .where(GraphEdgeRecord.project_id == project_id)
            .order_by(GraphEdgeRecord.ui_id)
        )
    ).all()

    annotation_rows = (
        await session.execute(
            sa.select(
                NodeColumnAnnotationRecord.node_id.label("node_ui_id"),
                NodeColumnAnnotationRecord.port,
                NodeColumnAnnotationRecord.column_name.label("column"),
                NodeColumnAnnotationRecord.description,
                NodeColumnAnnotationRecord.origin_key,
            )
            .where(NodeColumnAnnotationRecord.project_id == project_id)
            .order_by(
                NodeColumnAnnotationRecord.node_id,
                NodeColumnAnnotationRecord.port,
                NodeColumnAnnotationRecord.column_name,
            )
        )
    ).all()

    return GraphSnapshot(
        subgraphs=[GraphSubgraphSnapshot(**row._mapping) for row in subgraph_rows],
        nodes=[GraphNodeSnapshot(**row._mapping) for row in node_rows],
        edges=[GraphEdgeSnapshot(**row._mapping) for row in edge_rows],
        column_annotations=[ColumnAnnotationSnapshot(**row._mapping) for row in annotation_rows],
    )


def _ownership(
    *,
    project_id: str,
    user_id: str,
    organization_id: str,
    now: datetime,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "project_id": project_id,
        "user_id": user_id,
        "organization_id": organization_id,
        "created_at": now,
        "updated_at": now,
    }


async def insert_graph_snapshot(
    session: AsyncSession,
    snapshot: GraphSnapshot,
    *,
    project_id: str,
    user_id: str,
    organization_id: str,
    now: datetime,
) -> None:
    """Bulk-insert a snapshot whose ui_ids are already unique within the project."""
    ownership = {"project_id": project_id, "user_id": user_id, "organization_id": organization_id, "now": now}

    if snapshot.subgraphs:
        await session.execute(
            sa.insert(SubgraphRecord.__table__),
            [{**asdict(subgraph), **_ownership(**ownership)} for subgraph in snapshot.subgraphs],
        )
    if snapshot.nodes:
        await session.execute(
            sa.insert(GraphNodeRecord.__table__),
            [{**asdict(node), **_ownership(**ownership)} for node in snapshot.nodes],
        )
    if snapshot.edges:
        await session.execute(
            sa.insert(GraphEdgeRecord.__table__),
            [{**asdict(edge), **_ownership(**ownership)} for edge in snapshot.edges],
        )
    if snapshot.column_annotations:
        # Author of the copy becomes the author of the copied descriptions.
        await session.execute(
            sa.insert(NodeColumnAnnotationRecord.__table__),
            [
                {
                    "id": str(uuid.uuid4()),
                    "project_id": project_id,
                    "node_id": annotation.node_ui_id,
                    "port": annotation.port,
                    "column_name": annotation.column,
                    "description": annotation.description,
                    "origin_key": annotation.origin_key,
                    "description_updated_by": user_id,
                    "created_at": now,
                    "updated_at": now,
                }
                for annotation in snapshot.column_annotations
            ],
        )


async def delete_graph(session: AsyncSession, project_id: str) -> None:
    """Remove every graph element and node-attached file of a project."""
    await session.execute(sa.delete(GraphEdgeRecord).where(GraphEdgeRecord.project_id == project_id))
    await session.execute(
        sa.delete(NodeColumnAnnotationRecord).where(NodeColumnAnnotationRecord.project_id == project_id)
    )
    await session.execute(sa.delete(GraphNodeRecord).where(GraphNodeRecord.project_id == project_id))
    await session.execute(sa.delete(SubgraphRecord).where(SubgraphRecord.project_id == project_id))
    await session.execute(
        sa.delete(DVTServiceFileObjectRecord).where(DVTServiceFileObjectRecord.project_id == project_id)
    )


async def copy_service_file_objects(
    session: AsyncSession,
    *,
    organization_id: str,
    source_project_id: str,
    target_project_id: str,
    rewrites: Sequence[ServiceFilesPrefixRewrite],
    now: datetime,
) -> None:
    """Duplicate node-attached file objects of one project under remapped prefixes."""
    if not rewrites:
        return

    rows = (
        await session.execute(
            sa.select(DVTServiceFileObjectRecord).where(
                DVTServiceFileObjectRecord.organization_id == organization_id,
                DVTServiceFileObjectRecord.project_id == source_project_id,
            )
        )
    ).scalars().all()
    if not rows:
        return

    copied_paths: set[tuple[str, str]] = set()
    values = []
    for row in rows:
        full_path = f"{row.parent_path}/{row.name}".strip("/")
        for rewrite in rewrites:
            new_full_path = rebase_service_file_path(full_path, rewrite)
            if new_full_path is None:
                continue
            if "/" in new_full_path:
                new_parent_path, new_name = new_full_path.rsplit("/", 1)
            else:
                new_parent_path, new_name = "", new_full_path
            path_key = (new_parent_path, new_name)
            if path_key in copied_paths:
                continue
            copied_paths.add(path_key)
            values.append(
                {
                    "id": str(uuid.uuid4()),
                    "organization_id": organization_id,
                    "project_id": target_project_id,
                    "parent_path": new_parent_path,
                    "name": new_name,
                    "is_dir": row.is_dir,
                    "content": row.content,
                    "content_type": row.content_type,
                    "size": row.size,
                    "sha256": row.sha256,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            break

    if values:
        await session.execute(sa.insert(DVTServiceFileObjectRecord.__table__), values)
