from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.node_dsl.variables import normalize_variable_type
from src.node_dsl.variables.types import VariableType
from src.utils.project_variables import (
    normalize_project_variable_storage_payload,
    normalize_project_variables_storage_map,
    deserialize_project_variable_value,
)


class ProjectVariableDefinition(BaseModel):
    """Typed runtime representation of a project variable."""

    type: VariableType = Field(description="Тип переменной")
    value: Any = Field(description="Значение переменной")
    is_list_type: bool = Field(default=False, description="Является ли переменная списком")

    @model_validator(mode="after")
    def _deserialize_runtime_value(self) -> "ProjectVariableDefinition":
        normalized_payload = normalize_project_variable_storage_payload(
            {
                "type": self.type,
                "value": self.value,
                "is_list_type": self.is_list_type,
            },
            allow_legacy=False,
        )
        self.type = normalize_variable_type(normalized_payload["type"])
        self.is_list_type = normalized_payload["is_list_type"]
        self.value = deserialize_project_variable_value(
            variable_type=self.type,
            value=normalized_payload["value"],
            is_list_type=self.is_list_type,
        )
        return self


class ProjectVariables(BaseModel):
    """Project variables with both typed and raw-value views."""

    model_config = ConfigDict(from_attributes=True)

    variables: dict[str, ProjectVariableDefinition] | None = None

    @field_validator("variables", mode="before")
    @classmethod
    def _normalize_variables(
        cls,
        value: Any,
    ) -> dict[str, dict[str, Any]] | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError("Project variables must be a mapping.")
        return normalize_project_variables_storage_map(value, allow_legacy=True)

    @property
    def raw_values(self) -> dict[str, Any]:
        return {
            variable_name: variable_definition.value
            for variable_name, variable_definition in (self.variables or {}).items()
        }
