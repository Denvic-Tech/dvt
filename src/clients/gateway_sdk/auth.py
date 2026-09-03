from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AuthConfig:
    username: str | None = None
    password: str | None = None
    access_token: str | None = None
    api_token: str | None = None

    @property
    def has_username_password(self) -> bool:
        return bool(self.username and self.password)

    @property
    def has_access_token(self) -> bool:
        return bool(self.access_token)

    @property
    def has_api_token(self) -> bool:
        return bool(self.api_token)


def is_public_path(path: str) -> bool:
    return path.startswith("/public/")


def is_auth_sign_in_path(path: str) -> bool:
    return path == "/auth/sign-in"
