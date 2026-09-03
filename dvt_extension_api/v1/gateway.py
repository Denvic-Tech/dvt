"""FastAPI-facing types supported for extension routes."""

from src.modules.user.infra.fastapi.dependencies import (
    UserAccessOnly,
    UserAdminAccessOnly,
    UserSuperadminAccessOnly,
)

CurrentUserDep = UserAccessOnly
CurrentAdminDep = UserAdminAccessOnly
CurrentSuperadminDep = UserSuperadminAccessOnly

__all__ = ["CurrentAdminDep", "CurrentSuperadminDep", "CurrentUserDep"]
