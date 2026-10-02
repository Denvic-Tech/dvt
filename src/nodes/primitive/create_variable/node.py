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
    ICON_KEY = "create-variable"

    name: str = InputField(
        agent_description=(
            "Set the exact output variable name that downstream DVT expressions will reference. "
            "Use an intentional, unambiguous name; a matching existing variable is replaced in "
            "this node's output."
        ),
        description="Имя переменной",
    )
    type: VariableType = InputField(
        agent_description=(
            "Choose the declared VariableType matching the resolved value or, for lists, each "
            "element. Do not rely on an arbitrary string or object being accepted as another type; "
            "resolution and default validation enforce the declared variable contract."
        ),
        description="Тип переменной",
    )
    is_list_type: bool = InputField(
        agent_description=(
            "Set true when value resolves to a list of elements of the selected type. Leave false "
            "for a scalar. This is a literal schema setting and cannot be supplied as a DVT "
            "expression."
        ),
        default=False,
        description="Интерпретировать переменную как список значений указанного типа.",
        allow_expressions=False,
    )
    value: VariableValue = InputField(
        agent_description=(
            "Provide a value compatible with type and is_list_type, or a canonical DVT expression "
            "resolved against input_variables. Full execution requires referenced variables to "
            "resolve; metadata mode can retain unresolved values. Configure nullable/default "
            "deliberately for possible null results."
        ),
        description="Значение переменной",
        expression_policy="default",
    )
    nullable: bool = InputField(
        agent_description=(
            "Set true to permit a resolved null when no default is supplied. This is a literal "
            "schema setting. An explicit default takes precedence, including default=null; "
            "nullable=false alone does not override a supplied null default."
        ),
        default=False,
        description="Разрешить NULL, если значение переменной вычислилось в NULL и default не задан.",
        allow_expressions=False,
    )
    default: Any | UnsetType = InputField(
        agent_description=(
            "Optionally provide a literal fallback for a resolved null, matching type and "
            "is_list_type. Omission means no default; explicit default=null is supplied and can "
            "yield null even with nullable=false. Expressions are not allowed here. A default "
            "does not rescue missing variables, expression errors, or invalid non-null values."
        ),
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
