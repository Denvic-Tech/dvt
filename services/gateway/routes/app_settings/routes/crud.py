from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Query, status

from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.app_settings.domain.exceptions import (
    SettingNotFoundError,
    SettingReadOnlyError,
    SettingValidationError,
)
from src.modules.app_settings.public import helpers
from src.modules.user.infra.fastapi.dependencies import UserAdminAccessOnly

from ..helpers import (
    _actor_id,
    _iter_update_items,
    _map_settings_error,
    _settings_to_schema,
    _to_plain,
)
from ..schemas import (
    AppSettingsReadSchema,
    AppSettingsUpdateSchema,
)
from src.modules.app_settings.infra.schemas import AppSettingHistoryItemSchema

r = router = APIRouter()


@router.get("", response_model=AppSettingsReadSchema)
async def get_app_settings(
    session: AsyncSessionDepends,
    user: UserAdminAccessOnly,  # noqa: ARG001
) -> AppSettingsReadSchema:
    settings = await helpers.get_app_settings(session=session)
    return _settings_to_schema(settings)


@router.post("", response_model=AppSettingsReadSchema)
async def upsert_app_settings(
    request: AppSettingsUpdateSchema,
    session: AsyncSessionDepends,
    user: UserAdminAccessOnly,  # noqa: ARG001
) -> AppSettingsReadSchema:
    try:
        for key, value in _iter_update_items(request):
            await helpers.set_setting_value(
                key,
                value,
                session=session,
                changed_by=_actor_id(user),
            )
    except (SettingNotFoundError, SettingReadOnlyError, SettingValidationError) as exc:
        raise _map_settings_error(exc) from exc

    await session.commit()

    settings = await helpers.get_app_settings(session=session)
    return _settings_to_schema(settings)


@router.get("/{key}/history", response_model=list[AppSettingHistoryItemSchema])
async def get_app_setting_history(
    key: str,
    session: AsyncSessionDepends,
    user: UserAdminAccessOnly,  # noqa: ARG001
) -> list[AppSettingHistoryItemSchema]:
    try:
        history = await helpers.get_setting_history(key, session=session)
    except SettingNotFoundError as exc:
        raise _map_settings_error(exc) from exc
    return [AppSettingHistoryItemSchema.model_validate(item.__dict__) for item in history]


@router.get("/{key}", response_model=Any)
async def get_app_settings_by_key(
    key: str,
    session: AsyncSessionDepends,
    user: UserAdminAccessOnly,  # noqa: ARG001
) -> Any:
    try:
        settings = await helpers.get_app_settings(session=session)
        return _to_plain(settings.get(key))
    except (KeyError, ValueError, AttributeError, SettingNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="App setting key not found") from exc


@router.post("/{key}", response_model=Any, status_code=status.HTTP_201_CREATED)
async def set_app_settings_value(
    key: str,
    value: Annotated[Any, Body(embed=False)],
    session: AsyncSessionDepends,
    user: UserAdminAccessOnly,  # noqa: ARG001
) -> Any:
    try:
        saved = await helpers.set_setting_value(
            key,
            value,
            session=session,
            changed_by=_actor_id(user),
        )
        await session.commit()
        return saved
    except (SettingNotFoundError, SettingReadOnlyError, SettingValidationError) as exc:
        raise _map_settings_error(exc) from exc


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app_settings_value(
    key: str,
    session: AsyncSessionDepends,
    user: UserAdminAccessOnly,
) -> None:
    try:
        await helpers.delete_setting_value(
            key,
            session=session,
            changed_by=_actor_id(user),
        )
        await session.commit()
    except SettingNotFoundError as exc:
        raise _map_settings_error(exc) from exc
