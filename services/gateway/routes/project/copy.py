import re
import uuid
from copy import deepcopy
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter

from services.gateway.deps.project import UserProjectByPath

from src.crud import project as project_crud
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.file_storage.infra.db_models import DVTServiceFileObjectRecord
from src.modules.pipeline_graph.infra.db_models import (
    GraphEdgeRecord,
    GraphNodeRecord,
    SubgraphRecord,
)
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.schemas.http.project import ProjectReadSchema, ProjectUpdateSchema
from src.utils.access_control import build_owner_or_org_filters

router = APIRouter()


def bump_name(name: str) -> str:
    m = re.search(r"(.*)\s(\d+)$", name)
    if m:
        base = m.group(1)
        num = int(m.group(2)) + 1
        return f"{base} {num}"
    return f"{name} 2"


def _is_dvt_service_files_connection(value: object) -> bool:
    return isinstance(value, dict) and value.get("type") == "dvt_service_files"


def _extract_dvt_service_files_connection(input_values: object) -> dict | None:
    if not isinstance(input_values, dict):
        return None
    connection_input = input_values.get("connection")
    if not isinstance(connection_input, dict) or connection_input.get("__dvt_type") != "const":
        return None
    connection = connection_input.get("value")
    if not _is_dvt_service_files_connection(connection):
        return None
    return connection


def _copy_root_prefix(old_root_prefix: str, *, new_node_ui_id: str) -> str:
    parts = [part for part in old_root_prefix.strip("/").split("/") if part]
    if len(parts) >= 3 and parts[0] == "node-inputs":
        return "/".join(["node-inputs", new_node_ui_id, *parts[2:]])
    return f"node-inputs/{new_node_ui_id}/file"


def _rewrite_dvt_service_files_input_values(
    input_values: object,
    *,
    organization_id: str,
    new_project_id: str,
    new_node_ui_id: str,
) -> tuple[object, tuple[str, str] | None]:
    connection = _extract_dvt_service_files_connection(input_values)
    if connection is None:
        return input_values, None

    rewritten_input_values = deepcopy(input_values)
    rewritten_connection = rewritten_input_values["connection"]["value"]
    properties = dict(rewritten_connection.get("properties") or {})
    old_root_prefix = str(properties.get("root_prefix") or "").strip("/")
    new_root_prefix = _copy_root_prefix(old_root_prefix, new_node_ui_id=new_node_ui_id)

    properties.update(
        {
            "organization_id": organization_id,
            "project_id": new_project_id,
            "root_prefix": new_root_prefix,
        }
    )
    rewritten_connection["id"] = (
        f"dvt-service-files:{new_project_id}:{new_node_ui_id}:{new_root_prefix.rsplit('/', 1)[-1]}"
    )
    rewritten_connection["properties"] = properties
    return rewritten_input_values, (old_root_prefix, new_root_prefix)


def _replace_path_prefix(path: str, old_prefix: str, new_prefix: str) -> str | None:
    if not old_prefix:
        return None
    normalized = path.strip("/")
    if normalized == old_prefix:
        return new_prefix
    if normalized.startswith(f"{old_prefix}/"):
        return f"{new_prefix}{normalized[len(old_prefix):]}"
    return None


async def _copy_dvt_service_file_objects(
    *,
    session: AsyncSessionDepends,
    organization_id: str,
    old_project_id: str,
    new_project_id: str,
    root_prefix_pairs: list[tuple[str, str]],
    now: datetime,
) -> None:
    if not root_prefix_pairs:
        return

    rows = (
        await session.execute(
            sa.select(DVTServiceFileObjectRecord).where(
                DVTServiceFileObjectRecord.organization_id == organization_id,
                DVTServiceFileObjectRecord.project_id == old_project_id,
            )
        )
    ).scalars().all()
    if not rows:
        return

    copied_paths: set[tuple[str, str]] = set()
    values = []
    for row in rows:
        full_path = f"{row.parent_path}/{row.name}".strip("/")
        for old_prefix, new_prefix in root_prefix_pairs:
            new_full_path = _replace_path_prefix(full_path, old_prefix, new_prefix)
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
                    "project_id": new_project_id,
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


@router.post("/{project_id}/copy", response_model=ProjectReadSchema)
async def copy_project(
    project_id: str,
    data: ProjectUpdateSchema,
    session: AsyncSessionDepends,
    user: UserAccessOnly,
    project: UserProjectByPath,
) -> ProjectReadSchema:
    filters = [
        ProjectRecord.id == project_id,
        ProjectRecord.is_deleted == False,  # noqa: E712
    ]
    filters.extend(
        build_owner_or_org_filters(
            user=user,
            organization_column=ProjectRecord.organization_id,
            owner_column=ProjectRecord.user_id,
        )
    )

    payload = data.model_dump(exclude_unset=True)
    new_project_name = payload.get("name", bump_name(project.name))

    now = datetime.now(tz=UTC)
    new_project = ProjectRecord(
        id=str(uuid.uuid4()),
        name=new_project_name,
        user_id=project.user_id,
        organization_id=project.organization_id,
        is_deleted=False,
        created_at=now,
        updated_at=now,
    )

    session.add(new_project)
    await session.flush()

    subgraphs_rows = (
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
            ).where(SubgraphRecord.project_id == project_id)
        )
    ).all()

    subgraph_ui_id_map = {}
    if subgraphs_rows:
        subgraph_values = []
        for row in subgraphs_rows:
            new_subgraph_ui_id = f"subgraph_{uuid.uuid4()}"
            subgraph_ui_id_map[row.ui_id] = new_subgraph_ui_id
            subgraph_values.append(
                {
                    "id": str(uuid.uuid4()),
                    "ui_id": new_subgraph_ui_id,
                    "type": row.type,
                    "position_x": row.position_x,
                    "position_y": row.position_y,
                    "selected": row.selected,
                    "expanded": row.expanded,
                    "name": row.name,
                    "display_name": row.display_name,
                    "comment": row.comment,
                    "color": row.color,
                    "project_id": new_project.id,
                    "user_id": new_project.user_id,
                    "organization_id": new_project.organization_id,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        await session.execute(sa.insert(SubgraphRecord.__table__), subgraph_values)

    nodes_rows = (
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
                GraphNodeRecord.input_values,
                GraphNodeRecord.subgraph_id,
            ).where(GraphNodeRecord.project_id == project_id)
        )
    ).all()

    node_ui_id_map = {}
    service_file_root_prefix_pairs: list[tuple[str, str]] = []
    if nodes_rows:
        node_values = []
        for row in nodes_rows:
            new_node_ui_id = f"node_{uuid.uuid4()}"
            node_ui_id_map[row.ui_id] = new_node_ui_id
            input_values, service_file_root_prefix_pair = _rewrite_dvt_service_files_input_values(
                row.input_values,
                organization_id=new_project.organization_id,
                new_project_id=new_project.id,
                new_node_ui_id=new_node_ui_id,
            )
            if service_file_root_prefix_pair is not None:
                service_file_root_prefix_pairs.append(service_file_root_prefix_pair)
            node_values.append(
                {
                    "id": str(uuid.uuid4()),
                    "ui_id": new_node_ui_id,
                    "type": row.type,
                    "position_x": row.position_x,
                    "position_y": row.position_y,
                    "selected": row.selected,
                    "name": row.name,
                    "display_name": row.display_name,
                    "comment": row.comment,
                    "show_signal_io": row.show_signal_io,
                    "input_values": input_values,
                    "subgraph_id": subgraph_ui_id_map.get(row.subgraph_id, row.subgraph_id),
                    "project_id": new_project.id,
                    "user_id": new_project.user_id,
                    "organization_id": new_project.organization_id,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        await session.execute(sa.insert(GraphNodeRecord.__table__), node_values)
        await _copy_dvt_service_file_objects(
            session=session,
            organization_id=new_project.organization_id,
            old_project_id=project_id,
            new_project_id=new_project.id,
            root_prefix_pairs=service_file_root_prefix_pairs,
            now=now,
        )

    edges_rows = (
        await session.execute(
            sa.select(
                GraphEdgeRecord.ui_id,
                GraphEdgeRecord.type,
                GraphEdgeRecord.source,
                GraphEdgeRecord.source_handle,
                GraphEdgeRecord.target,
                GraphEdgeRecord.target_handle,
                GraphEdgeRecord.subgraph_id,
            ).where(GraphEdgeRecord.project_id == project_id)
        )
    ).all()

    if edges_rows:
        edge_values = [
            {
                "id": str(uuid.uuid4()),
                "ui_id": f"edge_{uuid.uuid4()}",
                "type": row.type,
                "source": node_ui_id_map.get(row.source, row.source),
                "source_handle": row.source_handle,
                "target": node_ui_id_map.get(row.target, row.target),
                "target_handle": row.target_handle,
                "subgraph_id": subgraph_ui_id_map.get(row.subgraph_id, row.subgraph_id),
                "project_id": new_project.id,
                "user_id": new_project.user_id,
                "organization_id": new_project.organization_id,
                "created_at": now,
                "updated_at": now,
            }
            for row in edges_rows
        ]
        await session.execute(sa.insert(GraphEdgeRecord.__table__), edge_values)

    await session.commit()
    await session.refresh(new_project)
    user_emails = await project_crud.get_user_emails_by_ids(
        session,
        user_ids=[project.user_id],
    )

    return ProjectReadSchema(
        **new_project.model_dump(),
        user_email=user_emails.get(project.user_id),
    )
