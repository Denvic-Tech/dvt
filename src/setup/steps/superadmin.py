from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from usrak.core.security import hash_password

from src import enums
from src.modules.user.infra.db_models import UserRecord
from src.setup import api as setup_api
from src.setup.dsl import BaseSetupStep, SetupStepField
from src.setup.exceptions import SetupConflictError, SetupValidationError


class SuperadminSetupPayload(BaseModel):
    email: str = Field(
        ...,
        description="Адрес электронная почты",
        json_schema_extra={"setup_label": "Email", "setup_type": "email"},
    )
    password: str = Field(
        ...,
        description="Пароль",
        json_schema_extra={
            "setup_label": "Password",
            "setup_type": "password",
            "sensitive": True,
        },
    )


class SuperadminSetupStep(BaseSetupStep):
    CODE = "superadmin"
    ORDER = 20
    TITLE = "Супер-пользователь"
    DESCRIPTION = "Создайте аккаунт супер-пользователя."
    SUBMIT_LABEL = "Создайте супер-пользователя."

    @classmethod
    async def is_completed(cls, session: AsyncSession) -> bool:
        return await setup_api.has_superadmin(session)

    @classmethod
    async def build_fields(
        cls,
        session: AsyncSession,
        *,
        completed: bool,
    ) -> list[SetupStepField]:
        user = await setup_api.get_first_superadmin(session)
        values = {"email": user.email} if user is not None else None
        return cls.build_fields_from_model(SuperadminSetupPayload, values=values)

    @classmethod
    async def submit(cls, session: AsyncSession, values: Mapping[str, Any]) -> None:
        if await setup_api.has_superadmin(session):
            raise SetupConflictError("Супер-пользователь уже существует.")

        organization = await setup_api.get_first_organization(session)
        if organization is None:
            raise SetupValidationError("Организация должна существовать для супер-пользователя.")

        payload = cls.validate_model(SuperadminSetupPayload, values)
        existing_user = await setup_api.get_user_by_email(session, payload.email)
        if existing_user is not None:
            raise SetupConflictError("Пользователь с таким email уже существует.")

        user = UserRecord(
            email=payload.email,
            user_name=payload.email,
            hashed_password=hash_password(payload.password),
            auth_provider="email",
            is_verified=True,
            is_active=True,
            role=enums.DVTDefaultRoles.SUPERADMIN.value,
            organization_id=organization.id,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
