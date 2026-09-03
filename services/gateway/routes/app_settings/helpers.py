from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel

from src.modules.app_settings.domain.exceptions import (
    SettingNotFoundError,
    SettingReadOnlyError,
    SettingValidationError,
)
from src.modules.app_settings.public import DVTAppSettings, constants

from .schemas import AppSettingsReadSchema, AppSettingsUpdateSchema


def _actor_id(user: Any) -> str | None:
    return getattr(user, "id", None)


def _map_settings_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SettingNotFoundError):
        return HTTPException(status_code=404, detail="App setting key not found")
    if isinstance(exc, (SettingReadOnlyError, SettingValidationError)):
        return HTTPException(status_code=422, detail=str(exc))
    raise exc


def _settings_to_schema(settings: DVTAppSettings) -> AppSettingsReadSchema:
    return AppSettingsReadSchema.model_validate(_to_plain(settings.as_dict()))


def _to_plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _to_plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_plain(item) for item in value]
    return value


def _iter_update_items(request: AppSettingsUpdateSchema):
    def iter_payload(values: dict[str, Any], parts: tuple[str, ...] = ()):
        for name, value in values.items():
            if value is None:
                continue
            key = ".".join((*parts, name))
            if isinstance(value, dict) and not constants.APP_SETTINGS_REGISTRY.contains(key):
                yield from iter_payload(value, (*parts, name))
            else:
                yield key, value

    payload = request.model_dump(exclude_unset=True, mode="json")
    yield from iter_payload(payload)
