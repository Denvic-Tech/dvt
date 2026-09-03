from fastapi import APIRouter

from .sql_query_to_metadata import router as sql_query_to_metadata_router
from .DDL import router as DDL_router
from .csv import router as csv_router

router = APIRouter(prefix="/utils", tags=["Utilities"])
router.include_router(sql_query_to_metadata_router)
router.include_router(DDL_router)
router.include_router(csv_router)
