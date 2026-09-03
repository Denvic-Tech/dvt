from fastapi import APIRouter, Depends

from src.modules.user.infra.fastapi.dependencies import get_user_admin_access_only

from .user_crud import router as user_crud_router

router = APIRouter(
    prefix="/admin",
    tags=["Admin router"],
    dependencies=[Depends(get_user_admin_access_only)],
)

router.include_router(user_crud_router, prefix="/users", tags=["Admin Users CRUD"])
