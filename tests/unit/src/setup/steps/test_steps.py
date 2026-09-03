from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models import OrganizationRecord
from src.modules.user.infra.db_models import UserRecord
from src.modules.app_settings import DVTApplicationSettings
from src.modules.app_settings.public import helpers as app_settings_helpers
from src.setup import api as setup_api
from src.setup.exceptions import SetupConflictError, SetupValidationError
from src.setup.steps.app_settings import AppSettingsSetupStep
from src.setup.steps.organization import OrganizationSetupStep
from src.setup.steps.superadmin import SuperadminSetupStep


@pytest.mark.asyncio
async def test_organization_step_builds_fields_with_existing_value(monkeypatch):
    monkeypatch.setattr(
        setup_api,
        "get_first_organization",
        AsyncMock(return_value=OrganizationRecord(name="Acme")),
    )

    fields = await OrganizationSetupStep.build_fields(MagicMock(), completed=True)

    assert len(fields) == 1
    assert fields[0].key == "name"
    assert fields[0].value == "Acme"


@pytest.mark.asyncio
async def test_organization_step_creates_first_organization(monkeypatch):
    monkeypatch.setattr(setup_api, "has_organization", AsyncMock(return_value=False))
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    await OrganizationSetupStep.submit(session, {"name": "Acme"})

    organization = session.add.call_args.args[0]
    assert isinstance(organization, OrganizationRecord)
    assert organization.name == "Acme"
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(organization)


@pytest.mark.asyncio
async def test_superadmin_step_requires_organization_first(monkeypatch):
    monkeypatch.setattr(setup_api, "has_superadmin", AsyncMock(return_value=False))
    monkeypatch.setattr(setup_api, "get_first_organization", AsyncMock(return_value=None))

    with pytest.raises(SetupValidationError, match="Организация"):
        await SuperadminSetupStep.submit(MagicMock(), {"email": "admin@example.com", "password": "secret"})


@pytest.mark.asyncio
async def test_superadmin_step_creates_user(monkeypatch):
    monkeypatch.setattr(setup_api, "has_superadmin", AsyncMock(return_value=False))
    monkeypatch.setattr(
        setup_api,
        "get_first_organization",
        AsyncMock(return_value=OrganizationRecord(id="org-1", name="Acme")),
    )
    monkeypatch.setattr(setup_api, "get_user_by_email", AsyncMock(return_value=None))
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    await SuperadminSetupStep.submit(
        session,
        {"email": "admin@example.com", "password": "secret"},
    )

    user = session.add.call_args.args[0]
    assert isinstance(user, UserRecord)
    assert user.email == "admin@example.com"
    assert user.organization_id == "org-1"
    assert user.hashed_password != "secret"
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(user)


@pytest.mark.asyncio
async def test_superadmin_step_rejects_existing_superadmin(monkeypatch):
    monkeypatch.setattr(setup_api, "has_superadmin", AsyncMock(return_value=True))

    with pytest.raises(SetupConflictError, match="Супер-пользователь уже существует"):
        await SuperadminSetupStep.submit(MagicMock(), {"email": "admin@example.com", "password": "secret"})


@pytest.mark.asyncio
async def test_app_settings_step_builds_fields_from_bootstrap_metadata(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(
        app_settings_helpers,
        "list_bootstrap_required_fields",
        MagicMock(return_value=["dcc.url"]),
    )
    monkeypatch.setattr(
        app_settings_helpers,
        "get_app_settings",
        AsyncMock(
            return_value=DVTApplicationSettings.build_runtime_model(
                DVTApplicationSettings.validate_values(
                    {
                        **DVTApplicationSettings.default_values(),
                        "dcc.url": "https://example.test",
                    }
                )
            )
        ),
    )

    fields = await AppSettingsSetupStep.build_fields(session, completed=False)

    assert len(fields) == 1
    assert fields[0].key == "dcc.url"
    assert fields[0].label == "DCC URL"
    assert fields[0].type == "text"
    assert fields[0].value == "https://example.test"


@pytest.mark.asyncio
async def test_app_config_step_rejects_unknown_fields(monkeypatch):
    monkeypatch.setattr(
        app_settings_helpers,
        "list_bootstrap_required_fields",
        MagicMock(return_value=["dcc.url"]),
    )

    with pytest.raises(SetupValidationError, match="not allowed"):
        await AppSettingsSetupStep.submit(MagicMock(), {"runtime.datetime_precision": "Seconds"})


@pytest.mark.asyncio
async def test_app_config_step_persists_allowed_fields(monkeypatch):
    session = MagicMock()
    session.commit = AsyncMock()
    set_setting_value = AsyncMock()
    monkeypatch.setattr(
        app_settings_helpers,
        "list_bootstrap_required_fields",
        MagicMock(return_value=["dcc.url"]),
    )
    monkeypatch.setattr(AppSettingsSetupStep, "is_completed", AsyncMock(return_value=False))
    monkeypatch.setattr(
        app_settings_helpers,
        "set_setting_value",
        set_setting_value,
    )

    await AppSettingsSetupStep.submit(session, {"dcc.url": "https://example.test"})

    set_setting_value.assert_awaited_once_with(
        "dcc.url",
        "https://example.test",
        session=session,
        changed_by="bootstrap",
    )
    session.commit.assert_awaited_once()
