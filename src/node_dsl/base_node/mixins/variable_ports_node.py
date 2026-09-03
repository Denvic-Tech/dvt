from collections.abc import Mapping
from typing import Any

from src.node_dsl.constants import NodeInputNames, NodeOutputNames
from src.node_dsl.input_expressions import ImmutableInputVariables
from src.node_dsl.node_typing import IO

from .base import BaseNodeMixin


class VariablePortsNodeMixin(BaseNodeMixin):
    input_variables: dict[str, IO.VARIABLE]
    output_variables: dict[str, IO.VARIABLE]

    @property
    def immutable_input_variables(self) -> ImmutableInputVariables:
        return ImmutableInputVariables({
            variable_name: variable.value
            for variable_name, variable in (self.input_variables or {}).items()
        })

    def _normalize_variable_ports(self) -> None:
        input_variables = getattr(self, NodeInputNames.VARIABLES, None)
        if not isinstance(input_variables, dict):
            input_variables = dict(input_variables or {})
        else:
            input_variables = dict(input_variables)

        existing_output_variables = getattr(self, NodeOutputNames.VARIABLES, None)
        if not isinstance(existing_output_variables, dict):
            existing_output_variables = {}
        else:
            existing_output_variables = dict(existing_output_variables)

        existing_output_variables.update(input_variables)

        self.input_variables = input_variables
        self.output_variables = existing_output_variables

    @staticmethod
    def _iter_variable_items(value: Any) -> list[tuple[str, Any]]:
        if isinstance(value, Mapping):
            if isinstance(value.get("name"), str) and value["name"]:
                return [(value["name"], value)]
            return [
                (key, item)
                for key, item in value.items()
                if isinstance(key, str) and key
            ]

        variable_name = getattr(value, "name", None)
        if isinstance(variable_name, str) and variable_name:
            return [(variable_name, value)]

        return []

    def _refresh_output_variables(self) -> None:
        output_variables = dict(self.input_variables or {})
        output_variables.update(self.output_variables or {})

        for output_field in self._output_field_instances.values():
            if output_field.attr_name in NodeOutputNames:
                continue

            if output_field.resolved_type is not IO.VARIABLE:
                continue

            for variable_name, variable_value in self._iter_variable_items(
                getattr(self, output_field.attr_name, None)
            ):
                output_variables[variable_name] = variable_value

        self.output_variables = output_variables
