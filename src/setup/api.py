from __future__ import annotations

from typing import Any, Mapping

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import enums
from src.models import OrganizationRecord
from src.modules.user.infra.db_models import UserRecord
from src.setup.dsl import BaseSetupStep, SetupStatus
from src.setup.dsl._init_steps import init_setup_steps
from src.setup.dsl.registry import get as get_setup_step_cls
from src.setup.dsl.registry import get_all as get_all_setup_step_classes
from src.setup.exceptions import SetupConflictError, SetupValidationError


def get_registered_setup_steps() -> list[type[BaseSetupStep]]:
    init_setup_steps()
    return get_all_setup_step_classes()


def resolve_setup_step(step_code: str) -> type[BaseSetupStep]:
    init_setup_steps()
    try:
        return get_setup_step_cls(step_code)
    except KeyError as exc:
        raise SetupValidationError(f"Setup step '{step_code}' is not registered.") from exc


async def get_setup_status(session: AsyncSession) -> SetupStatus:
    steps = [await step_cls.get_status(session) for step_cls in get_registered_setup_steps()]
    return SetupStatus(
        initialized=all(step.completed for step in steps),
        steps=steps,
    )


async def is_setup_initialized(session: AsyncSession) -> bool:
    status = await get_setup_status(session)
    return status.initialized


async def submit_setup_step(
    session: AsyncSession,
    *,
    step_code: str,
    values: Mapping[str, Any],
) -> SetupStatus:
    if await is_setup_initialized(session):
        raise SetupConflictError("Setup is already completed.")

    step_cls = resolve_setup_step(step_code)
    await step_cls.submit(session, values)
    return await get_setup_status(session)


async def has_superadmin(session: AsyncSession) -> bool:
    stmt = sa.select(UserRecord.id).where(UserRecord.role == enums.DVTDefaultRoles.SUPERADMIN.value)
    result = await session.execute(stmt)
    return result.scalars().first() is not None


async def has_organization(session: AsyncSession) -> bool:
    stmt = sa.select(OrganizationRecord.id).limit(1)
    result = await session.execute(stmt)
    return result.scalars().first() is not None


async def get_first_organization(session: AsyncSession) -> OrganizationRecord | None:
    stmt = sa.select(OrganizationRecord).order_by(OrganizationRecord.created_at.asc(), OrganizationRecord.id.asc()).limit(1)
    return (await session.execute(stmt)).scalars().first()


async def get_first_superadmin(session: AsyncSession) -> UserRecord | None:
    stmt = (
        sa.select(UserRecord)
        .where(UserRecord.role == enums.DVTDefaultRoles.SUPERADMIN.value)
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def get_user_by_email(session: AsyncSession, email: str) -> UserRecord | None:
    stmt = sa.select(UserRecord).where(UserRecord.email == email)
    return (await session.execute(stmt)).scalars().first()
