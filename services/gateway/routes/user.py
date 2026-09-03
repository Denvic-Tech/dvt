from fastapi import APIRouter

from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.schemas.http.user import UserReadSchema

r = router = APIRouter(prefix="/user", tags=["User"])


@router.get(
    "/info",
    response_model=UserReadSchema,
    summary="Получить информацию о пользователе"
)
async def get_user_info(
        user: UserAccessOnly,
):
    """Получить информацию о пользователе."""
    return UserReadSchema.model_validate(user, from_attributes=True)
