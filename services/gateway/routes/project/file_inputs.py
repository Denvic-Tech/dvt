from pathlib import PurePosixPath
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Path, Query, UploadFile
from pydantic import BaseModel, Field

from services.gateway.deps.dvt_service_files import (
    _root_prefix,
    build_dvt_service_files_storage,
)

from src.crud import graph as graph_crud, project as project_crud
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.file_storage.domain.value_objects import StorageEntryName
from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.node_dsl.core.input_values import NodeInputConstantValue, NodeInputValues
from src.utils.access_control import get_access_scope

import config

router = r = APIRouter(tags=["Project File Inputs"])


_SUPPORTED_NODE_EXTENSIONS: dict[str, set[str]] = {
    "LoadCSV": {".csv"},
    "LoadExcel": {".xls", ".xlsx", ".xlsm"},
    "LoadJSON": {".json"},
    "LoadParquet": {".parquet"},
}


class NodeFileInputResponse(BaseModel):
    node_id: str
    input_name: str
    filename: str | None = None
    path: str | None = None
    size: int | None = None
    connection: dict[str, Any] | None = None
    input_values_patch: NodeInputValues = Field(default_factory=dict)


def _const(value: object) -> dict:
    return NodeInputConstantValue(value=value).model_dump(by_alias=True)


def _extension(filename: str) -> str:
    return PurePosixPath(filename).suffix.lower()


def _build_connection_payload(
    *,
    organization_id: str,
    project_id: str,
    node_id: str,
    input_name: str,
) -> dict:
    return {
        "id": f"dvt-service-files:{project_id}:{node_id}:{input_name}",
        "name": "DVT service files",
        "kind": "file",
        "type": "dvt_service_files",
        "driver": None,
        "driver_options": None,
        "properties": {
            "organization_id": organization_id,
            "project_id": project_id,
            "root_prefix": _root_prefix(node_id, input_name),
        },
        "secrets": {},
        "labels": {},
        "metadata": {"system": True, "purpose": "node-file-input"},
        "extra": {},
    }


def _validate_node_file(node: GraphNodeRecord, *, filename: str) -> None:
    allowed_extensions = _SUPPORTED_NODE_EXTENSIONS.get(node.name)
    if allowed_extensions is None:
        raise HTTPException(
            status_code=400,
            detail=f"Node '{node.name}' does not support local file inputs.",
        )
    ext = _extension(filename)
    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File extension '{ext or '<none>'}' is not allowed for {node.name}. "
                f"Allowed: {sorted(allowed_extensions)}"
            ),
        )


async def _get_project_and_node(
    *,
    project_id: str,
    node_id: str,
    session: AsyncSessionDepends,
    user: UserAccessOnly,
):
    access_scope = get_access_scope(user)
    project = (
        await project_crud.get_projects_by(
            session=session,
            organization_id=access_scope.organization_id,
            owner_user_id=access_scope.owner_user_id,
            project_id=project_id,
        )
    ).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    node = (
        await graph_crud.get_graph_nodes(
            session,
            GraphNodeRecord.project_id == project.id,
            GraphNodeRecord.ui_id == node_id,
        )
    ).first()
    if node is None:
        raise HTTPException(status_code=404, detail="Graph node not found")

    return project, node


@r.post(
    "/{node_id}/file-inputs/{input_name}",
    response_model=NodeFileInputResponse,
)
async def upload_node_file_input(
    project_id: Annotated[str, Path(description="Project ID")],
    node_id: Annotated[str, Path(description="Graph node UI ID")],
    input_name: Annotated[str, Path(description="Logical file input name")],
    session: AsyncSessionDepends,
    user: UserAccessOnly,
    file: UploadFile = File(...),
):
    filename = StorageEntryName.from_raw(file.filename or "upload.bin").value
    project, node = await _get_project_and_node(
        project_id=project_id,
        node_id=node_id,
        session=session,
        user=user,
    )
    _validate_node_file(node, filename=filename)

    content = await file.read()
    if len(content) > config.OTHER.NODE_FILE_UPLOAD_MAX_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "File exceeds maximum allowed size of "
                f"{config.OTHER.NODE_FILE_UPLOAD_MAX_SIZE_BYTES} bytes"
            ),
        )

    storage = build_dvt_service_files_storage(
        organization_id=project.organization_id,
        project_id=project.id,
        node_id=node.ui_id,
        input_name=input_name,
    )
    await storage.upload_file(
        path="",
        filename=filename,
        content=content,
        content_type=file.content_type,
    )

    connection = _build_connection_payload(
        organization_id=project.organization_id,
        project_id=project.id,
        node_id=node.ui_id,
        input_name=input_name,
    )
    input_values_patch = {
        "connection": _const(connection),
        "path": _const(filename),
    }
    return NodeFileInputResponse(
        node_id=node.ui_id,
        input_name=input_name,
        filename=filename,
        path=filename,
        size=len(content),
        connection=connection,
        input_values_patch=input_values_patch,
    )


@r.delete(
    "/{node_id}/file-inputs/{input_name}",
    response_model=NodeFileInputResponse,
)
async def delete_node_file_input(
    project_id: Annotated[str, Path(description="Project ID")],
    node_id: Annotated[str, Path(description="Graph node UI ID")],
    input_name: Annotated[str, Path(description="Logical file input name")],
    path: Annotated[str, Query(description="Relative path returned by upload response")],
    session: AsyncSessionDepends,
    user: UserAccessOnly,
):
    project, node = await _get_project_and_node(
        project_id=project_id,
        node_id=node_id,
        session=session,
        user=user,
    )
    storage = build_dvt_service_files_storage(
        organization_id=project.organization_id,
        project_id=project.id,
        node_id=node.ui_id,
        input_name=input_name,
    )
    await storage.delete_files(paths=[path])
    return NodeFileInputResponse(
        node_id=node.ui_id,
        input_name=input_name,
        filename=PurePosixPath(path).name or None,
        path=None,
    )
