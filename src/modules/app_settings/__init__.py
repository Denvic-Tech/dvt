"""Application settings bounded context."""

from .domain import AppSettings
from .public import (
    APP_SETTINGS_REGISTRY,
    DccSettings,
    DVTApplicationSettings,
    DVTAppSettings,
    RuntimeSettings,
    delete_setting_value,
    ensure_setting_value,
    get_app_setting_definitions,
    get_app_settings,
    get_setting_definition,
    get_setting_history,
    get_setting_setup_type,
    get_setting_value,
    get_unfilled_required_fields,
    list_bootstrap_required_fields,
    list_required_fields,
    set_setting_value,
)

__all__ = [
    "APP_SETTINGS_REGISTRY",
    "AppSettings",
    "DVTAppSettings",
    "DVTApplicationSettings",
    "DccSettings",
    "RuntimeSettings",
    "delete_setting_value",
    "ensure_setting_value",
    "get_app_setting_definitions",
    "get_app_settings",
    "get_setting_definition",
    "get_setting_history",
    "get_setting_setup_type",
    "get_setting_value",
    "get_unfilled_required_fields",
    "list_bootstrap_required_fields",
    "list_required_fields",
    "set_setting_value",
]


# TODO: при "плохих" настройках (не проходящих валидацию или сваливающихся в исключение), если есть для них default или его можно безопасно вычислить - не падать с ошибкой, а исправлять настройку.