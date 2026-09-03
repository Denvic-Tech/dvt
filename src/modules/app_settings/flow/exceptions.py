from src.exception_registry import RegisteredException


class AppSettingsFlowError(RegisteredException):
    category = "APP_SETTINGS_FLOW_ERROR"
