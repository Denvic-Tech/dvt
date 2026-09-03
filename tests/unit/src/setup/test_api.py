from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src import setup
from src.setup import api as setup_api
from src.setup import SetupConflictError, SetupValidationError
from src.setup.dsl import SetupStatus, SetupStep, SetupStepField


def make_step(*, code: str, completed: bool) -> SetupStep:
    return SetupStep(
        code=code,
        title=code.title(),
        description=f"{code} description",
        submit_label=f"Submit {code}",
        completed=completed,
        fields=[
            SetupStepField(
                key="field",
                label="Field",
                type="text",
                required=True,
                nullable=False,
            )
        ],
    )


@pytest.mark.asyncio
async def test_get_setup_status_aggregates_registered_steps(monkeypatch):
    session = MagicMock()
    first_step = MagicMock()
    first_step.get_status = AsyncMock(return_value=make_step(code="organization", completed=True))
    second_step = MagicMock()
    second_step.get_status = AsyncMock(return_value=make_step(code="app_config", completed=False))
    monkeypatch.setattr(setup_api, "get_registered_setup_steps", lambda: [first_step, second_step])

    status = await setup.get_setup_status(session)

    assert status == SetupStatus(
        initialized=False,
        steps=[
            make_step(code="organization", completed=True),
            make_step(code="app_config", completed=False),
        ],
    )


@pytest.mark.asyncio
async def test_submit_setup_step_dispatches_to_registered_step(monkeypatch):
    session = MagicMock()
    step_cls = MagicMock()
    step_cls.submit = AsyncMock()
    expected_status = SetupStatus(initialized=False, steps=[make_step(code="organization", completed=True)])
    monkeypatch.setattr(setup_api, "is_setup_initialized", AsyncMock(return_value=False))
    monkeypatch.setattr(setup_api, "resolve_setup_step", MagicMock(return_value=step_cls))
    monkeypatch.setattr(setup_api, "get_setup_status", AsyncMock(return_value=expected_status))

    result = await setup.submit_setup_step(
        session,
        step_code="organization",
        values={"name": "Acme"},
    )

    assert result is expected_status
    setup_api.resolve_setup_step.assert_called_once_with("organization")
    step_cls.submit.assert_awaited_once_with(session, {"name": "Acme"})


@pytest.mark.asyncio
async def test_submit_setup_step_rejects_when_setup_is_already_completed(monkeypatch):
    monkeypatch.setattr(setup_api, "is_setup_initialized", AsyncMock(return_value=True))

    with pytest.raises(SetupConflictError, match="already completed"):
        await setup.submit_setup_step(
            MagicMock(),
            step_code="organization",
            values={"name": "Acme"},
        )


def test_resolve_setup_step_raises_validation_error_for_unknown_code(monkeypatch):
    monkeypatch.setattr("src.setup.api.get_setup_step_cls", MagicMock(side_effect=KeyError("missing")))

    with pytest.raises(SetupValidationError, match="not registered"):
        setup.resolve_setup_step("missing")
