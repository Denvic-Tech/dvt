from src.exception_registry import RegisteredException


class AppSettingsDomainError(RegisteredException):
    name = "APP_SETTINGS_DOMAIN_ERROR"
    code = "APP_SETTINGS_001"
    category = "APP_SETTINGS_DOMAIN_ERROR"
    description = "Application settings domain error"

    def __init__(self, description: str | None = None):
        super().__init__(description)
        Exception.__init__(self, description or self.description)


class SettingNotFoundError(AppSettingsDomainError):
    name = "APP_SETTING_NOT_FOUND"
    code = "APP_SETTINGS_002"
    category = "APP_SETTING_NOT_FOUND"
    description = "Application setting was not found"


class SettingValidationError(AppSettingsDomainError):
    name = "APP_SETTING_VALIDATION_ERROR"
    code = "APP_SETTINGS_003"
    category = "APP_SETTING_VALIDATION_ERROR"
    description = "Application setting value is invalid"


class SettingReadOnlyError(AppSettingsDomainError):
    name = "APP_SETTING_READ_ONLY"
    code = "APP_SETTINGS_004"
    category = "APP_SETTING_READ_ONLY"
    description = "Application setting is read-only"
