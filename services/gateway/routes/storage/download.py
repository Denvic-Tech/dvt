from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from services.gateway.routes.storage.deps import get_file_storage_facade
from services.gateway.routes.storage.http_errors import to_http_exception

from src.logger import logger
from src.modules.file_storage import FileStorageFacade

r = router = APIRouter()


@r.get("/presign", response_model=str)
async def generate_presigned_download_url(
        connection_id: str,
        filename: str,
        path: str,
        storage: FileStorageFacade = Depends(get_file_storage_facade),
):
    try:
        return await storage.generate_download_presign(
            path=path,
            filename=filename,
        )
    except HTTPException as exc:
        logger.exception(f"Failed to presign: {exc}")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Failed to presign: {exc}")
        raise to_http_exception(exc) from exc


@r.get("/file")
async def download_file_via_gateway(
        connection_id: str,
        filename: str,
        path: str,
        storage: FileStorageFacade = Depends(get_file_storage_facade),
):
    try:
        payload = await storage.download_file(
            path=path,
            filename=filename,
        )
        headers = {"Content-Disposition": f'attachment; filename="{payload.filename}"'}
        return StreamingResponse(
            iter([payload.content]),
            media_type=payload.media_type or "application/octet-stream",
            headers=headers,
        )
    except HTTPException as exc:
        logger.exception(f"Failed to presign: {exc}")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Failed to presign: {exc}")
        raise to_http_exception(exc) from exc
