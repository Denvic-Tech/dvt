from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from src.modules.app_settings.domain.definitions import SettingDefinition


class FernetSettingValueCipher:
    def __init__(self, key: str | bytes | Fernet | None) -> None:
        if key is None:
            raise RuntimeError("config.SECURITY.FERNET_KEY is required for app settings secrets.")
        if isinstance(key, Fernet):
            self._fernet = key
            return
        self._fernet = Fernet(key.encode("utf-8") if isinstance(key, str) else key)

    def encrypt(self, value: str | None, *, definition: SettingDefinition) -> str | None:
        if value is None or not definition.secret:
            return value
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str | None, *, definition: SettingDefinition) -> str | None:
        if value is None or not definition.secret:
            return value
        try:
            return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError(f"Could not decrypt app setting '{definition.key}'.") from exc
