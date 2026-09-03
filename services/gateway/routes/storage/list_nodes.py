from fastapi import APIRouter, Depends, HTTPException, Query

from services.gateway.routes.storage.deps import get_file_storage_facade
from services.gateway.routes.storage.http_errors import to_http_exception

from src.logger import logger
from src.modules.file_storage import FileStorageFacade, storage_tree_to_http_schema
from src.modules.file_storage.infra.schemas.user_file_tree import UserFileTreeSchema

r = router = APIRouter()


@r.get("", response_model=UserFileTreeSchema)
async def list_any_storage(
    connection_id: str,
    path: str = Query("", description="Path or prefix to list"),
    max_items: int = Query(1000, ge=1, le=10000),
    storage: FileStorageFacade = Depends(get_file_storage_facade),
):
    try:
        tree = await storage.list_nodes(
            path=path,
            max_items=max_items,
        )
        return storage_tree_to_http_schema(tree)
    except HTTPException as exc:
        logger.exception(f"Failed to list storage: {exc}")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Failed to list storage: {exc}")
        raise to_http_exception(exc) from exc
