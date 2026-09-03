from fastapi import APIRouter

from .routes.crud import router as crud_router
from .routes.definitions import router as definitions_router

router = APIRouter()

router.include_router(definitions_router, prefix="/app-settings", tags=["App Settings"])
router.include_router(crud_router, prefix="/app-settings", tags=["App Settings"])
