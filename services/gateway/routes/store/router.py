from fastapi import APIRouter
from .key_value import r as store_router

router = APIRouter()

router.include_router(store_router, prefix="/store", tags=["Store API"])
