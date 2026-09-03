from fastapi import APIRouter

from src.modules.app_settings.infra.mappers import setting_definition_to_schema
from src.modules.app_settings.infra.schemas import AppSettingDefinitionSchema
from src.modules.app_settings.public import helpers
from src.modules.user.infra.fastapi.dependencies import UserAdminAccessOnly

r = router = APIRouter()


@router.get("/definitions", response_model=list[AppSettingDefinitionSchema])
async def get_app_setting_definitions(
    user: UserAdminAccessOnly,  # noqa: ARG001
) -> list[AppSettingDefinitionSchema]:
    return [
        setting_definition_to_schema(definition)
        for definition in helpers.get_app_setting_definitions()
    ]
