from typing import Any, Dict

import dask
import dask.dataframe as dd
import pandas as pd

from src.node_dsl import DFOutputBaseNode, InputField, NodeValidationError, OutputField
from src.node_dsl.hooks import on_validation
from src.node_dsl.node_typing import IO
from src.node_dsl.variables import VariableOutput, build_variable_output, is_unresolved_value


class ConvertVariablesToDataFrame(DFOutputBaseNode):
    TITLE = "Variables → DataFrame"
    EMOJI = "☑️"
    CATEGORY = "Transform"
    CACHABLE = False

    input_variables: Dict[str, IO.VARIABLE] = InputField(
        default={},
        description="Input variables",
        allow_multiple_connections=True,
        force_handle_visible=True
    )
    output: dd.DataFrame = OutputField()

    @staticmethod
    def _normalize_input_variables(raw_input_variables: Any) -> dict[str, VariableOutput]:
        if not isinstance(raw_input_variables, dict):
            raise NodeValidationError("`input_variables` must be a dictionary.")

        normalized_variables: dict[str, VariableOutput] = {}
        for variable_name, payload in raw_input_variables.items():
            if not isinstance(variable_name, str) or not variable_name:
                raise NodeValidationError("Input variable names must be non-empty strings.")
            try:
                normalized_variables[variable_name] = build_variable_output(variable_name, payload)
            except ValueError as exc:
                raise NodeValidationError(
                    f"Invalid input variable '{variable_name}': {exc}"
                ) from exc

        return normalized_variables

    @staticmethod
    def _get_pandas_dtype(variable: VariableOutput) -> str | object:
        if variable.is_list_type:
            return "object"

        dtype_mapping = {
            IO.STRING: "string",
            IO.BOOLEAN: "boolean",
            IO.INT: "Int64",
            IO.FLOAT: "float64",
            IO.DATETIME: "datetime64[ns]",
            IO.TIMEDELTA: "timedelta64[ns]",
            IO.JSON: "object",
        }
        return dtype_mapping.get(variable.type, "object")

    @classmethod
    def _build_pdf(
        cls,
        input_variables: dict[str, VariableOutput],
        *,
        include_values: bool,
    ) -> pd.DataFrame:
        data: dict[str, pd.Series] = {}
        for variable_name, variable in input_variables.items():
            if include_values and is_unresolved_value(variable.value):
                raise NodeValidationError(
                    f"Input variable '{variable_name}' has unresolved value and cannot be converted "
                    "to a DataFrame in full execution mode."
                )

            values = [variable.value] if include_values else []
            data[variable_name] = pd.Series(values, dtype=cls._get_pandas_dtype(variable))

        return pd.DataFrame(data)

    @on_validation(name="Validate input variables not empty")
    def validate_input_variables_not_empty(self):
        self.input_variables = self._normalize_input_variables(self.input_variables or {})
        if not self.input_variables:
            raise NodeValidationError(f"Input variables are empty")

    def process(self):
        self.input_variables = self._normalize_input_variables(self.input_variables or {})
        if not self.input_variables:
            raise NodeValidationError("Input variables are empty")

        pdf = self._build_pdf(self.input_variables, include_values=True)
        with dask.config.set({"dataframe.convert-string": False}):
            self.output = dd.from_pandas(pdf, npartitions=1)

    def process_metadata(self) -> None:
        self.input_variables = self._normalize_input_variables(self.input_variables or {})
        if not self.input_variables:
            raise NodeValidationError("Input variables are empty")

        pdf = self._build_pdf(self.input_variables, include_values=False)
        with dask.config.set({"dataframe.convert-string": False}):
            self.output = dd.from_pandas(pdf, npartitions=1)
