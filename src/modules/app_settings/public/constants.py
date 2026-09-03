from ..infra.cache import InMemoryAppSettingsCache
from .dvt_app_settings import DVTApplicationSettings, DVTAppSettings

APP_SETTINGS_REGISTRY = DVTApplicationSettings
_CACHE = InMemoryAppSettingsCache[DVTAppSettings]()
