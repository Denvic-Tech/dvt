from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.db import async_engine

import config

from ..domain.definitions import SettingDefinition
from ..domain.entities import SettingChange
from ..domain.registry import SettingsRegistry
from ..domain.services import infer_setup_type, is_required_unfilled
from ..flow.providers import AppSettingsProvider
from ..flow.use_cases import (
    DeleteSettingValueUseCase,
    EnsureSettingUseCase,
    GetAppSettingDefinitionsUseCase,
    GetAppSettingsUseCase,
    GetSettingHistoryUseCase,
    SetSettingValueUseCase,
)
from ..infra.encryption import FernetSettingValueCipher
from ..infra.repositories import SQLAppSettingsRepository
from ..infra.sources import (
    EmptySecretSettingsSource,
    EnvironmentSettingsSource,
)
from .constants import _CACHE, APP_SETTINGS_REGISTRY
from .dvt_app_settings import DVTAppSettings


@asynccontextmanager
async def _session_scope(session: AsyncSession | None) -> AsyncIterator[tuple[AsyncSession, bool]]:
    if session is not None:
        yield session, False
        return

    async with AsyncSession(async_engine) as created_session:
        yield created_session, True


def _build_provider(
    session: AsyncSession,
    *,
    registry: type[SettingsRegistry[DVTAppSettings]] = APP_SETTINGS_REGISTRY,
) -> AppSettingsProvider[DVTAppSettings]:
    repository = SQLAppSettingsRepository(
        session,
        registry=registry,
        cipher=FernetSettingValueCipher(config.SECURITY.FERNET_KEY),
    )
    return AppSettingsProvider(
        registry=registry,
        repository=repository,
        cache=_CACHE,
        env_source=EnvironmentSettingsSource(),
        secret_source=EmptySecretSettingsSource(),
    )


async def get_app_settings(
    session: AsyncSession | None = None,
) -> DVTAppSettings:
    async with _session_scope(session) as (resolved_session, _):
        provider = _build_provider(resolved_session)
        return await GetAppSettingsUseCase(provider).execute()


async def get_setting_value(key: str, session: AsyncSession | None = None) -> Any:
    settings = await get_app_settings(session=session)
    return settings.get(key)


async def set_setting_value(
    key: str,
    value: Any,
    session: AsyncSession | None = None,
    *,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> Any:
    async with _session_scope(session) as (resolved_session, owns_session):
        provider = _build_provider(resolved_session)
        saved = await SetSettingValueUseCase(provider).execute(
            key,
            value,
            changed_by=changed_by,
            change_reason=change_reason,
        )
        if owns_session:
            await resolved_session.commit()
        return saved.value


async def delete_setting_value(
    key: str,
    session: AsyncSession | None = None,
    *,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> bool:
    async with _session_scope(session) as (resolved_session, owns_session):
        provider = _build_provider(resolved_session)
        deleted = await DeleteSettingValueUseCase(provider).execute(
            key,
            changed_by=changed_by,
            change_reason=change_reason,
        )
        if owns_session:
            await resolved_session.commit()
        return deleted


async def get_setting_history(
    key: str,
    session: AsyncSession | None = None,
) -> list[SettingChange]:
    async with _session_scope(session) as (resolved_session, _):
        provider = _build_provider(resolved_session)
        return await GetSettingHistoryUseCase(provider).execute(key)


async def ensure_setting_value(
    key: str,
    factory: Callable[[], Any],
    session: AsyncSession | None = None,
    *,
    changed_by: str | None = None,
    change_reason: str | None = None,
    force: bool = False,
) -> Any:
    async with _session_scope(session) as (resolved_session, owns_session):
        provider = _build_provider(resolved_session)
        value = await EnsureSettingUseCase(provider).execute(
            key,
            factory,
            changed_by=changed_by,
            change_reason=change_reason,
            force=force,
        )
        if owns_session:
            await resolved_session.commit()
        return value


def get_app_setting_definitions() -> list[SettingDefinition]:
    return GetAppSettingDefinitionsUseCase(APP_SETTINGS_REGISTRY).execute()


def list_required_fields() -> list[str]:
    return [
        definition.key
        for definition in APP_SETTINGS_REGISTRY.all_definitions()
        if definition.required
    ]


def list_bootstrap_required_fields() -> list[str]:
    return [
        definition.key
        for definition in APP_SETTINGS_REGISTRY.all_definitions()
        if definition.bootstrap and definition.required
    ]


async def get_unfilled_required_fields(
    session: AsyncSession | None = None,
    *,
    bootstrap_only: bool = False,
) -> list[str]:
    settings = await get_app_settings(session=session)
    return [
        definition.key
        for definition in APP_SETTINGS_REGISTRY.all_definitions()
        if (definition.bootstrap or not bootstrap_only)
        and is_required_unfilled(settings.get, definition)
    ]


def get_setting_definition(key: str) -> SettingDefinition:
    return APP_SETTINGS_REGISTRY.get_definition(key)


def get_setting_setup_type(definition: SettingDefinition) -> str:
    return infer_setup_type(definition.key, definition)
