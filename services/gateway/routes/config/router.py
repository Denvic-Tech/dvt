from fastapi import APIRouter

from .expressions import router as expressions_router

router = APIRouter()

router.include_router(expressions_router, prefix="/config", tags=["Config"])
