from __future__ import annotations

from src.modules.app_settings import DVTApplicationSettings
from src.modules.app_settings.infra.schema_factory import build_app_settings_schema

AppSettingsReadSchema = build_app_settings_schema(
    DVTApplicationSettings,
    name="AppSettingsReadSchema",
    update=False,
)
AppSettingsUpdateSchema = build_app_settings_schema(
    DVTApplicationSettings,
    name="AppSettingsUpdateSchema",
    update=True,
)
