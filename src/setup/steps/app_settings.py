from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.app_settings.public import helpers
from src.setup.dsl import BaseSetupStep, SetupStepField
from src.setup.exceptions import SetupConflictError, SetupValidationError


class AppSettingsSetupStep(BaseSetupStep):
    CODE = "app_settings"
    ORDER = 30
    TITLE = "Конфигурация DVT"
    DESCRIPTION = "Сконфигурируйте DVT."
    SUBMIT_LABEL = "Сохранить конфигурацию"

    @classmethod
    async def is_completed(cls, session: AsyncSession) -> bool:
        unfilled = await helpers.get_unfilled_required_fields(
            session=session,
            bootstrap_only=True,
        )
        return len(unfilled) == 0

    @classmethod
    async def build_fields(
        cls,
        session: AsyncSession,
        *,
        completed: bool,
    ) -> list[SetupStepField]:
        bootstrap_keys = helpers.list_bootstrap_required_fields()
        runtime_settings = await helpers.get_app_settings(session=session)

        result: list[SetupStepField] = []
        for key in bootstrap_keys:
            definition = helpers.get_setting_definition(key)
            value = None
            if not definition.secret:
                value = cls.serialize_field_value(runtime_settings.get(key))

            result.append(
                cls.build_field(
                    key=key,
                    label=definition.setup_label or key.replace(".", " ").strip().title(),
                    field_type=helpers.get_setting_setup_type(definition),
                    required=definition.required,
                    nullable=not definition.required,
                    value=value,
                )
            )
        return result

    @classmethod
    async def submit(cls, session: AsyncSession, values: Mapping[str, Any]) -> None:
        bootstrap_keys = helpers.list_bootstrap_required_fields()
        cls.ensure_allowed_keys(values, allowed_keys=bootstrap_keys)

        payload: dict[str, Any] = {}
        for key, value in values.items():
            annotation = helpers.get_setting_definition(key).type_
            payload[key] = cls.validate_field_value(key=key, annotation=annotation, value=value)

        payload = {key: value for key, value in payload.items() if value is not None}
        if not payload:
            raise SetupValidationError("Переданы пустые значения.")

        if await cls.is_completed(session):
            raise SetupConflictError("Конфигурация уже создана.")

        for key, value in payload.items():
            await helpers.set_setting_value(
                key,
                value,
                session=session,
                changed_by="bootstrap",
            )

        await session.commit()
