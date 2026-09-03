from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, Field


SetupFieldType: TypeAlias = Literal["text", "password", "email", "number", "boolean"]
SetupFieldValue: TypeAlias = str | int | float | bool


class SetupStepField(BaseModel):
    key: str = Field(..., description="Unique field key within the setup step.")
    label: str = Field(..., description="Human-readable field label.")
    type: SetupFieldType = Field(..., description="Frontend field type.")
    required: bool = Field(..., description="Whether the field must be submitted.")
    nullable: bool = Field(..., description="Whether null is allowed as a value.")
    value: SetupFieldValue | None = Field(
        default=None,
        description="Optional current value to prefill the setup form.",
    )


class SetupStep(BaseModel):
    code: str = Field(..., description="Unique setup step code.")
    title: str = Field(..., description="Human-readable setup step title.")
    description: str | None = Field(
        default=None,
        description="Optional human-readable setup step description.",
    )
    submit_label: str = Field(..., description="Label for the submit action.")
    completed: bool = Field(..., description="Whether the setup step is completed.")
    fields: list[SetupStepField] = Field(
        default_factory=list,
        description="Fields required to submit the setup step.",
    )


class SetupStatus(BaseModel):
    initialized: bool = Field(..., description="Is DVT fully initialized?")
    steps: list[SetupStep] = Field(
        default_factory=list,
        description="Ordered statuses of all setup steps.",
    )


class SetupStepSubmitRequest(BaseModel):
    values: dict[str, Any] = Field(
        default_factory=dict,
        description="Setup step payload keyed by setup field key.",
    )
