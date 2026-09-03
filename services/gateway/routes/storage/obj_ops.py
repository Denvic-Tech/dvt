from fastapi import APIRouter, Body, Depends, HTTPException

from services.gateway.routes.storage.deps import get_file_storage_facade
from services.gateway.routes.storage.http_errors import to_http_exception

from src.logger import logger
from src.modules.file_storage import FileStorageFacade
from src.modules.file_storage.infra.schemas.operations import (
    DeleteFilesIn,
    DeleteFolderIn,
    MovePathIn,
    RenamePathIn,
)
from src.schemas.http.common import CommonResponse

r = router = APIRouter()


@r.post("/folder/create", status_code=200, response_model=CommonResponse)
async def create_folder(
        connection_id: str,
        folder_name: str = Body(..., embed=True, description="Name of the folder to create"),
        path: str = Body("", embed=True, description="Path prefix where to create the folder"),
        storage: FileStorageFacade = Depends(get_file_storage_facade),
):
    try:
        await storage.create_folder(
            path=path,
            folder_name=folder_name,
        )
        return CommonResponse(
            success=True,
            message="Folder created successfully"
        )
    except HTTPException as exc:
        logger.exception(f"Failed to create folder: {exc}")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Failed to create folder: {exc}")
        raise to_http_exception(exc) from exc


@r.post("/files/delete", response_model=CommonResponse)
async def delete_files(
        connection_id: str,
        data: DeleteFilesIn,
        storage: FileStorageFacade = Depends(get_file_storage_facade),
):
    try:
        res = await storage.delete_files(
            paths=data.paths,
        )
        ok = res.deleted_count >= 0 and not res.errors
        return CommonResponse(success=ok, message=f"Deleted: {res.deleted_count}")
    except HTTPException as exc:
        logger.exception(f"Failed to delete a file: {exc}")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Failed to delete a file: {exc}")
        raise to_http_exception(exc) from exc


@r.post("/path/rename", status_code=200, response_model=CommonResponse)
async def rename_path(
        connection_id: str,
        data: RenamePathIn,
        storage: FileStorageFacade = Depends(get_file_storage_facade),
):
    try:
        await storage.rename_path(
            path=data.path,
            new_name=data.new_name,
        )
        return CommonResponse(success=True, message="Path renamed successfully")
    except HTTPException as exc:
        logger.exception(f"Failed to rename: {exc}")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Failed to rename: {exc}")
        raise to_http_exception(exc) from exc


@r.post("/path/move", status_code=200, response_model=CommonResponse)
async def move_path(
        connection_id: str,
        data: MovePathIn,
        storage: FileStorageFacade = Depends(get_file_storage_facade),
):
    try:
        await storage.move_path(
            path=data.path,
            target_path=data.target_path,
        )
        return CommonResponse(success=True, message="Path moved successfully")
    except HTTPException as exc:
        logger.exception(f"Failed to move: {exc}")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Failed to rename: {exc}")
        raise to_http_exception(exc) from exc


@r.post("/folder/delete", response_model=CommonResponse)
async def delete_folder(
        connection_id: str,
        data: DeleteFolderIn,
        storage: FileStorageFacade = Depends(get_file_storage_facade),
):
    try:
        res = await storage.delete_folder(
            path=data.path,
        )
        ok = res.deleted_count >= 0 and not res.errors
        return CommonResponse(success=ok, message=f"Deleted: {res.deleted_count}")
    except HTTPException as exc:
        logger.exception(f"Failed to delete a folder: {exc}")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Failed to delete a folder: {exc}")
        raise to_http_exception(exc) from exc
