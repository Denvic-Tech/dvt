from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from src.setup.dsl import BaseSetupStep, clear_setup_steps, get_all_setup_steps, init_setup_steps
from src.setup.dsl import registry as setup_registry


class _DummyLateStep(BaseSetupStep):
    CODE = "dummy_late"
    ORDER = 20
    TITLE = "Dummy Late"
    SUBMIT_LABEL = "Submit"

    @classmethod
    async def is_completed(self, session: AsyncSession) -> bool:
        return False

    @classmethod
    async def build_fields(self, session: AsyncSession, *, completed: bool):
        return []

    @classmethod
    async def submit(self, session: AsyncSession, values: Mapping[str, Any]) -> None:
        return None


class _DummyEarlyStep(BaseSetupStep):
    CODE = "dummy_early"
    ORDER = 10
    TITLE = "Dummy Early"
    SUBMIT_LABEL = "Submit"

    @classmethod
    async def is_completed(self, session: AsyncSession) -> bool:
        return False

    @classmethod
    async def build_fields(self, session: AsyncSession, *, completed: bool):
        return []

    @classmethod
    async def submit(self, session: AsyncSession, values: Mapping[str, Any]) -> None:
        return None


class _DummyDuplicateStep(BaseSetupStep):
    CODE = "dummy_early"
    ORDER = 30
    TITLE = "Dummy Duplicate"
    SUBMIT_LABEL = "Submit"

    @classmethod
    async def is_completed(self, session: AsyncSession) -> bool:
        return False

    @classmethod
    async def build_fields(self, session: AsyncSession, *, completed: bool):
        return []

    @classmethod
    async def submit(self, session: AsyncSession, values: Mapping[str, Any]) -> None:
        return None


def teardown_function() -> None:
    clear_setup_steps()
    init_setup_steps(force=True)


def test_registry_returns_steps_sorted_by_order():
    clear_setup_steps()
    setup_registry.add(_DummyLateStep)
    setup_registry.add(_DummyEarlyStep)

    assert [step.CODE for step in get_all_setup_steps()] == ["dummy_early", "dummy_late"]


def test_registry_rejects_duplicate_codes():
    clear_setup_steps()
    setup_registry.add(_DummyEarlyStep)

    try:
        setup_registry.add(_DummyDuplicateStep)
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("Expected duplicate setup step registration to fail.")


def test_init_setup_steps_registers_project_steps():
    clear_setup_steps()

    init_setup_steps(force=True)

    assert [step.CODE for step in get_all_setup_steps()] == [
        "organization",
        "superadmin",
        "app_settings",
    ]
