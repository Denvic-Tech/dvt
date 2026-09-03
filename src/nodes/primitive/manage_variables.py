from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, model_validator

from src.constants import UNSET
from src.node_dsl import IO, BaseNode, InputField, OutputField
from src.node_dsl.core.input_values import NodeInputExpressionValue
from src.node_dsl.variables import (
    VariableOutput,
    default_is_set,
    resolve_literal_input_value,
    resolve_variable_runtime_value,
)
from src.node_dsl.variables.types import VariableType
from src.types import UnsetType


class DefinedVariableInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: VariableType
    is_list_type: bool = False
    value: Any = None
    value_input: NodeInputExpressionValue | None = None
    nullable: bool = False
    default: Any | UnsetType = UNSET

    @model_validator(mode="after")
    def _validate_payload(self) -> "DefinedVariableInput":
        has_value = "value" in self.model_fields_set
        has_value_input = "value_input" in self.model_fields_set and self.value_input is not None
        if has_value == has_value_input:
            raise ValueError("Defined variable payload must define exactly one of 'value' or 'value_input'.")
        if default_is_set(self.default):
            resolve_literal_input_value(self.default, field_name="default")
        return self


class ManageVariables(BaseNode):
    TITLE = "Manage Variables"

    input_variables: Dict[str, IO.VARIABLE] = InputField(
        default={},
        description="Input variables",
        allow_multiple_connections=True,
        force_handle_visible=True,
    )
    defined_variables: Dict[str, DefinedVariableInput] = InputField(
        default={},
        description="Переменные для создания или переопределения",
        use_connection=False,
    )
    output_variables: Dict[str, IO.VARIABLE] = OutputField(
        description="Output variables",
        force_handle_visible=True,
    )

    def _apply_defined_variables(self, *, allow_unresolved: bool) -> None:
        for variable_name, variable_payload in (self.defined_variables or {}).items():
            normalized_payload = (
                variable_payload
                if isinstance(variable_payload, DefinedVariableInput)
                else DefinedVariableInput.model_validate(variable_payload)
            )
            raw_value = (
                normalized_payload.value_input
                if normalized_payload.value_input is not None
                else normalized_payload.value
            )
            resolved_value = resolve_variable_runtime_value(
                raw_value,
                variables=self.input_variables or {},
                variable_type=normalized_payload.type,
                allow_unresolved=allow_unresolved,
                nullable=normalized_payload.nullable,
                default_value=normalized_payload.default,
                is_list_type=normalized_payload.is_list_type,
            )
            self.output_variables[variable_name] = VariableOutput(
                name=variable_name,
                type=normalized_payload.type,
                value=resolved_value,
                var_type="user",
                is_list_type=normalized_payload.is_list_type,
            )

    def process(self) -> None:
        self._apply_defined_variables(allow_unresolved=False)

    def process_metadata(self) -> None:
        self._apply_defined_variables(allow_unresolved=True)
