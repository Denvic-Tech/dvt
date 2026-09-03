from fastapi import APIRouter

from .user.crud import router as user_crud_router

router = APIRouter(
    prefix="/admin",
    tags=["Admin API router"]
)

router.include_router(user_crud_router, prefix="/users", tags=["Admin API Users CRUD"])
