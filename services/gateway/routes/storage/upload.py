from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from services.gateway.routes.storage.deps import get_file_storage_facade
from services.gateway.routes.storage.http_errors import to_http_exception

from src.logger import logger
from src.modules.file_storage import (
    FileStorageFacade,
    presigned_upload_to_http_schema,
)
from src.modules.file_storage.infra.schemas.transfer import PresignedPostOut
from src.schemas.http.common import CommonResponse

r = router = APIRouter()


@r.get("/presign", response_model=PresignedPostOut)
async def generate_presigned_upload_url_post(
        connection_id: str,
        path: str,
        content_type_prefix: str,
        filename: Optional[str] = None,
        storage: FileStorageFacade = Depends(get_file_storage_facade),
):
    try:
        payload = await storage.generate_upload_presign(
            path=path,
            filename=filename or "",
            content_type_prefix=content_type_prefix,
        )
        return presigned_upload_to_http_schema(payload)
    except HTTPException as exc:
        logger.exception(f"Failed to presign: {exc}")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Failed to presign: {exc}")
        raise to_http_exception(exc) from exc


@r.post("/file", response_model=CommonResponse)
async def upload_file_via_gateway(
        connection_id: str,
        path: str = Form(""),
        file: UploadFile = File(...),
        storage: FileStorageFacade = Depends(get_file_storage_facade),
):
    try:
        content = await file.read()
        await storage.upload_file(
            path=path,
            filename=file.filename or "upload.bin",
            content=content,
            content_type=file.content_type,
        )
        return CommonResponse(success=True, message="File uploaded successfully")
    except HTTPException as exc:
        logger.exception(f"Failed to upload: {exc}")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Failed to upload: {exc}")
        raise to_http_exception(exc) from exc
