from fastapi import APIRouter

from services.gateway.routes.storage.upload import router as upload_router
from services.gateway.routes.storage.download import router as download_router
from services.gateway.routes.storage.list_nodes import router as list_nodes_router
from services.gateway.routes.storage.obj_ops import router as obj_ops_router

router = APIRouter()

router.include_router(upload_router, prefix="/storage/upload", tags=["Storage Upload"])
router.include_router(download_router, prefix="/storage/download", tags=["Storage Download"])
router.include_router(list_nodes_router, prefix="/storage/list", tags=["Storage List Nodes"])
router.include_router(obj_ops_router, prefix="/storage", tags=["Storage Objects Operations"])
