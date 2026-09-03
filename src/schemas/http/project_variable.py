from typing import Any, Dict

from pydantic import BaseModel, Field, model_validator

from src.node_dsl.variables import normalize_variable_type
from src.node_dsl.variables.types import VariableType
from src.utils.project_variables import normalize_project_variable_storage_payload


class ProjectVariableBase(BaseModel):
    """Typed project variable payload used by the HTTP API."""

    type: VariableType = Field(..., description="Тип переменной")
    value: Any = Field(..., description="Значение переменной")
    is_list_type: bool = Field(default=False, description="Является ли переменная списком")

    @model_validator(mode="after")
    def _normalize_payload(self) -> "ProjectVariableBase":
        normalized_payload = normalize_project_variable_storage_payload(
            {
                "type": self.type,
                "value": self.value,
                "is_list_type": self.is_list_type,
            },
            allow_legacy=False,
        )
        self.type = normalize_variable_type(normalized_payload["type"])
        self.value = normalized_payload["value"]
        self.is_list_type = normalized_payload["is_list_type"]
        return self


class ProjectVariableCreate(ProjectVariableBase):
    """Schema for creating a project variable."""


class ProjectVariableUpdate(ProjectVariableBase):
    """Schema for updating a project variable."""


class ProjectVariableRead(ProjectVariableBase):
    """Schema for reading a project variable."""

    key: str = Field(..., description="Ключ переменной")


class ProjectVariablesBulkUpdate(BaseModel):
    """Schema for bulk project variable updates."""

    variables: Dict[str, ProjectVariableBase] = Field(
        ...,
        description="Словарь typed-переменных для обновления",
    )
