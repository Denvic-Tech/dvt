from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import OrganizationRecord
from src.setup import api as setup_api
from src.setup.dsl import BaseSetupStep, SetupStepField
from src.setup.exceptions import SetupConflictError


class OrganizationSetupPayload(BaseModel):
    name: str = Field(
        ...,
        description="Имя первой организации.",
        json_schema_extra={"setup_label": "Имя организации"},
    )


class OrganizationSetupStep(BaseSetupStep):
    CODE = "organization"
    ORDER = 10
    TITLE = "Организация"
    DESCRIPTION = "Создайте первую организацию."
    SUBMIT_LABEL = "Сохранить организацию"

    @classmethod
    async def is_completed(cls, session: AsyncSession) -> bool:
        return await setup_api.has_organization(session)

    @classmethod
    async def build_fields(
        cls,
        session: AsyncSession,
        *,
        completed: bool,
    ) -> list[SetupStepField]:
        organization = await setup_api.get_first_organization(session)
        values = {"name": organization.name} if organization is not None else None
        return cls.build_fields_from_model(OrganizationSetupPayload, values=values)

    @classmethod
    async def submit(cls, session: AsyncSession, values: Mapping[str, Any]) -> None:
        if await setup_api.has_organization(session):
            raise SetupConflictError("Первая организация уже создана.")

        payload = cls.validate_model(OrganizationSetupPayload, values)
        organization = OrganizationRecord(name=payload.name)
        session.add(organization)
        await session.commit()
        await session.refresh(organization)
