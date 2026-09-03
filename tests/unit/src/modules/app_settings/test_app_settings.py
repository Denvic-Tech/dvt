from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass
from typing import Literal, get_type_hints

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pydantic import BaseModel

from src.modules.app_settings.domain import (
    Setting,
    SettingGroup,
    SettingsNamespace,
    SettingsRegistry,
)
from src.modules.app_settings.domain.definitions import SettingDefinition
from src.modules.app_settings.infra.db_models import AppSettingChangeRecord, AppSettingValueRecord
from src.modules.app_settings.infra.mappers import setting_definition_to_schema
from src.modules.app_settings.public import constants, helpers
from src.modules.app_settings.public.dvt_app_settings import (
    DateTimePrecision,
    DccSettings,
    DVTAppSettings,
    OOMGuardConfig,
)


@pytest_asyncio.fixture(autouse=True)
async def clear_app_settings_cache():
    await constants._CACHE.invalidate()
    yield
    await constants._CACHE.invalidate()


def test_registry_contains_declared_settings():
    keys = {definition.key for definition in constants.APP_SETTINGS_REGISTRY.all_definitions()}

    assert {
        "dcc.connector_id",
        "dcc.url",
        "dcc.username",
        "dcc.password",
        "runtime.oom_guard",
    } <= keys
    assert helpers.list_bootstrap_required_fields() == []


def test_dvt_settings_are_typed_frozen_dataclasses():
    settings = constants.APP_SETTINGS_REGISTRY.build_runtime_model(
        constants.APP_SETTINGS_REGISTRY.validate_values({})
    )

    assert get_type_hints(helpers.get_app_settings)["return"] is DVTAppSettings
    assert is_dataclass(DVTAppSettings)
    assert is_dataclass(DccSettings)
    assert isinstance(settings, DVTAppSettings)
    assert isinstance(settings.dcc, DccSettings)
    with pytest.raises(FrozenInstanceError):
        settings.dcc.url = "https://dcc.example"


def test_get_app_setting_definitions_returns_registry_definitions():
    definitions = helpers.get_app_setting_definitions()
    definitions_by_key = {definition.key: definition for definition in definitions}

    assert all(isinstance(definition, SettingDefinition) for definition in definitions)
    assert "dcc.password" in definitions_by_key
    assert "runtime.oom_guard" in definitions_by_key
    assert definitions_by_key["dcc.password"].required is False
    assert not hasattr(definitions_by_key["dcc.password"], "unfilled")


def test_setting_definition_mapper_serializes_metadata():
    definitions = {
        definition.key: definition
        for definition in helpers.get_app_setting_definitions()
    }

    password_schema = setting_definition_to_schema(definitions["dcc.password"])
    datetime_precision_schema = setting_definition_to_schema(
        definitions["runtime.datetime_precision"]
    )
    runtime_schema = setting_definition_to_schema(definitions["runtime.oom_guard"])

    assert password_schema.model_dump()["key"] == "dcc.password"
    assert password_schema.value_type == {"type": "string"}
    assert password_schema.nullable is True
    assert password_schema.required is False
    assert password_schema.secret is True
    assert password_schema.setup_type == "password"
    assert "unfilled" not in password_schema.model_dump()
    assert datetime_precision_schema.value_type["type"] == "string"
    assert datetime_precision_schema.value_type["enum"] == [
        "Nanoseconds",
        "Microseconds",
        "Seconds",
    ]
    assert runtime_schema.value_type["type"] == "object"
    assert set(runtime_schema.value_type["properties"]) >= {
        "mode",
        "host_threshold_percent",
        "worker_threshold_type",
        "worker_threshold_percent",
        "worker_threshold_mb",
    }
    assert runtime_schema.default == {
        "mode": "DISABLED",
        "host_threshold_percent": None,
        "worker_threshold_type": None,
        "worker_threshold_percent": None,
        "worker_threshold_mb": None,
    }


def test_setting_definition_mapper_resolves_complex_annotations():
    class DemoPayload(BaseModel):
        status: Literal["enabled", "disabled"]

    literal_schema = setting_definition_to_schema(
        SettingDefinition(
            namespace="demo",
            group=None,
            name="literal",
            type_=Literal["alpha", "beta"],
            default="alpha",
            ge=None,
            le=None,
            min_length=None,
            max_length=None,
            description=None,
            secret=False,
            runtime_editable=True,
            bootstrap=False,
            required=False,
            read_env=False,
            env_var=None,
            setup_label=None,
            setup_type=None,
        )
    )
    union_schema = setting_definition_to_schema(
        SettingDefinition(
            namespace="demo",
            group=None,
            name="union",
            type_=int | str | None,
            default=None,
            ge=None,
            le=None,
            min_length=None,
            max_length=None,
            description=None,
            secret=False,
            runtime_editable=True,
            bootstrap=False,
            required=False,
            read_env=False,
            env_var=None,
            setup_label=None,
            setup_type=None,
        )
    )
    model_schema = setting_definition_to_schema(
        SettingDefinition(
            namespace="demo",
            group=None,
            name="payload",
            type_=DemoPayload,
            default=DemoPayload(status="enabled"),
            ge=None,
            le=None,
            min_length=None,
            max_length=None,
            description=None,
            secret=False,
            runtime_editable=True,
            bootstrap=False,
            required=False,
            read_env=False,
            env_var=None,
            setup_label=None,
            setup_type=None,
        )
    )

    assert literal_schema.value_type == {
        "enum": ["alpha", "beta"],
        "type": "string",
    }
    assert union_schema.nullable is True
    assert union_schema.value_type == {
        "anyOf": [{"type": "integer"}, {"type": "string"}]
    }
    assert model_schema.value_type["type"] == "object"
    assert model_schema.value_type["properties"]["status"]["enum"] == [
        "enabled",
        "disabled",
    ]
    assert model_schema.default == {"status": "enabled"}


def test_oom_guard_config_is_pydantic_model():
    config = OOMGuardConfig(mode="HOST_PRESSURE", host_threshold_percent=80)

    assert isinstance(config, BaseModel)
    assert config.model_dump(mode="json")["mode"] == "HOST_PRESSURE"


def test_datetime_precision_defaults_to_microseconds():
    defaults = constants.APP_SETTINGS_REGISTRY.default_values()

    assert defaults["runtime.datetime_precision"] == DateTimePrecision.MICROSECONDS


def test_registry_supports_optional_groups():
    class GroupedSettings(SettingsRegistry):
        demo = SettingsNamespace(
            flat=Setting(str, default="flat-value"),
            nested=SettingGroup(
                enabled=Setting(bool, default=False),
            ),
        )

    settings = GroupedSettings.build_runtime_model(GroupedSettings.validate_values({}))

    assert {definition.key for definition in GroupedSettings.all_definitions()} == {
        "demo.flat",
        "demo.nested.enabled",
    }
    assert settings.demo.flat == "flat-value"
    assert settings.demo.nested.enabled is False
    assert settings.get("demo.nested.enabled") is False
    assert settings.as_dict()["demo"]["nested"]["enabled"] is False


@pytest.mark.asyncio
async def test_get_app_settings_persists_and_encrypts_secret(
    async_test_db_session,
):
    settings = await helpers.get_app_settings(session=async_test_db_session)
    assert settings.dcc.password is None

    await helpers.set_setting_value(
        "dcc.password",
        "db-password",
        session=async_test_db_session,
        changed_by="tester",
    )
    await async_test_db_session.commit()

    db_settings = await helpers.get_app_settings(session=async_test_db_session)
    assert db_settings.dcc.password == "db-password"

    row = (
        await async_test_db_session.execute(
            sa.select(AppSettingValueRecord).where(AppSettingValueRecord.key == "dcc.password")
        )
    ).scalars().one()
    assert row.value is not None
    assert "db-password" not in row.value

    history_rows = (
        await async_test_db_session.execute(
            sa.select(AppSettingChangeRecord).where(AppSettingChangeRecord.key == "dcc.password")
        )
    ).scalars().all()
    assert len(history_rows) == 1
    assert "db-password" not in history_rows[0].new_value

    history = await helpers.get_setting_history("dcc.password", session=async_test_db_session)
    assert history[0].new_value == "db-password"


@pytest.mark.asyncio
async def test_set_setting_value_validates_oom_guard(async_test_db_session):
    with pytest.raises(Exception, match="host_threshold_percent"):
        await helpers.set_setting_value(
            "runtime.oom_guard",
            {"mode": "HOST_PRESSURE"},
            session=async_test_db_session,
        )


@pytest.mark.asyncio
async def test_delete_setting_value_falls_back_to_default(async_test_db_session):
    await helpers.set_setting_value("dcc.url", "https://dcc.example", session=async_test_db_session)
    await async_test_db_session.commit()

    settings = await helpers.get_app_settings(session=async_test_db_session)
    assert settings.dcc.url == "https://dcc.example"

    deleted = await helpers.delete_setting_value("dcc.url", session=async_test_db_session)
    await async_test_db_session.commit()

    assert deleted is True
    settings = await helpers.get_app_settings(session=async_test_db_session)
    assert settings.dcc.url is None
