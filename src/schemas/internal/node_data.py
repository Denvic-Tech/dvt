from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.node_dsl.core.input_values.helpers import parse_node_runtime_input_value
from src.node_dsl.core.input_values.types import (
    NodeRuntimeInputValue,
    NodeRuntimeInputValues,
)


class NodeData(BaseModel):
    name: str = Field(description="Имя ноды")
    store_enabled: bool | None = Field(default=False, description="Сохранение данных ноды в кэш")
    inputs: NodeRuntimeInputValues = Field(
        description="Список входных полей ({field_name: NodeRuntimeInputValue})"
    )

    @field_validator("inputs", mode="before")
    @classmethod
    def _normalize_inputs(cls, value: Any) -> NodeRuntimeInputValues:
        if not isinstance(value, dict):
            raise ValueError("NodeData.inputs must be a dictionary.")

        normalized: dict[str, NodeRuntimeInputValue] = {}
        for input_name, raw_input in value.items():
            parsed_runtime_value = parse_node_runtime_input_value(raw_input)
            if parsed_runtime_value is not None:
                normalized[input_name] = parsed_runtime_value
                continue

            raise ValueError(
                f"NodeData.inputs['{input_name}'] must use canonical '__dvt_type' payloads."
            )

        return normalized

    class Config:
        extra = "allow"
