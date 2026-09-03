from typing import TYPE_CHECKING

from pydantic import BaseModel

from src.node_dsl.exceptions import NodeValidationError
from src.node_dsl.variables.system_variables import build_system_variable_type_map
from src.node_dsl.variables import VariableOutput

from .base import BaseNodeMixin

if TYPE_CHECKING:
    from src.node_dsl import IO


class SystemVariablesNodeMixin(BaseNodeMixin):
    output_variables: dict[str, "IO.VARIABLE"]

    def emit_system_variables(self, model_instance: BaseModel) -> None:
        system_variables_model = self.SYSTEM_VARIABLES_MODEL
        if system_variables_model is None:
            raise NodeValidationError(
                f"Node '{self.__class__.__name__}' does not declare SYSTEM_VARIABLES_MODEL."
            )
        if not isinstance(model_instance, BaseModel):
            raise TypeError("System variables must be provided as a pydantic model instance.")

        validated_instance = (
            model_instance
            if isinstance(model_instance, system_variables_model)
            else system_variables_model.model_validate(model_instance.model_dump())
        )
        system_variable_types = build_system_variable_type_map(system_variables_model)

        next_output_variables = dict(self.output_variables or {})
        for variable_name, variable_value in validated_instance.model_dump(exclude_unset=True).items():
            next_output_variables[variable_name] = VariableOutput(
                name=variable_name,
                type=system_variable_types[variable_name],
                value=variable_value,
                var_type="system",
            )

        self.output_variables = next_output_variables
