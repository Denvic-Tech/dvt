from typing import Any, Dict, Literal

from src.node_dsl import BaseNode, InputField, IO, OutputField
from src.node_dsl.hooks import on_validation
from src.node_dsl.variables import (
    VariableOutput,
    VariableValue,
    default_is_set,
    resolve_literal_input_value,
    resolve_variable_runtime_value,
)
from src.node_dsl.variables.types import VariableType
from src.constants import UNSET
from src.types import UnsetType


class CreateVariable(BaseNode):
    TITLE = "Create Variable"

    name: str = InputField(description="Имя переменной")
    type: VariableType = InputField(description="Тип переменной")
    is_list_type: bool = InputField(
        default=False,
        description="Интерпретировать переменную как список значений указанного типа.",
        allow_expressions=False,
    )
    value: VariableValue = InputField(
        description="Значение переменной",
        expression_policy="default",
    )
    nullable: bool = InputField(
        default=False,
        description="Разрешить NULL, если значение переменной вычислилось в NULL и default не задан.",
        allow_expressions=False,
    )
    default: Any | UnsetType = InputField(
        default=UNSET,
        description="Литеральное значение по умолчанию, если значение переменной вычислилось в NULL.",
        allow_expressions=False,
        use_connection=False,
    )

    output_variables: Dict[str, IO.VARIABLE] = OutputField(
        description="Output variables",
        force_handle_visible=True,
    )

    @on_validation
    def validate_default_value(self) -> None:
        if default_is_set(self.default):
            resolve_literal_input_value(self.default, field_name="default")

    def _emit_variable(self, *, allow_unresolved: bool) -> None:
        self.validate_default_value()
        self.output_variables[self.name] = VariableOutput(
            name=self.name,
            type=self.type,
            value=resolve_variable_runtime_value(
                self.value,
                variables=self.input_variables or {},
                variable_type=self.type,
                allow_unresolved=allow_unresolved,
                nullable=self.nullable,
                default_value=self.default,
                is_list_type=self.is_list_type,
            ),
            var_type="user",
            is_list_type=self.is_list_type,
        )

    def process(self) -> None:
        self._emit_variable(allow_unresolved=False)

    def process_metadata(self) -> None:
        self._emit_variable(allow_unresolved=True)
