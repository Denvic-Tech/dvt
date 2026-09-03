from fastapi import APIRouter

from .database import router as database_router
from .schema import router as schema_router
from .table import router as table_router

router = APIRouter(prefix="/ddl", tags=["DDL Utilities"])
router.include_router(database_router)
router.include_router(schema_router)
router.include_router(table_router)
