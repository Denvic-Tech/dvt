from typing import Optional

from dask import dataframe as dd
from pydantic import Field

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, NodeValidationError, OutputField
from src.node_dsl.hooks import on_validation
from src.node_dsl.node_mixins.column_rules import (
    RuleModel,
    contract_runtime_inputs,
    resolve_input_bindings,
)
from src.node_dsl.node_typing import IO


class ColumnBinding(RuleModel):
    source: str | None = None
    target: str = Field(min_length=1)
    input_bindings: dict[str, str] = Field(default_factory=dict)


class SetColumnToDataFrame(DFOutputBaseNode):
    TITLE = "Add column to DataFrame"
    CATEGORY = "Transform"
    EXPERIMENTAL = True
    TAGS = ["Unstable"]

    df: dd.DataFrame = InputField(
        agent_description=(
            "Experimental assignment node: inspect existing fields and indexes before attaching an "
            "external Series."
        ),
    )
    column_data: IO.COLUMN = InputField(
        agent_description=(
            "Connect Series data aligned to the target DataFrame index. Matching lengths alone do "
            "not ensure matching rows; verify alignment and missing values."
        ),
        description="Данные колонки",
        allow_multiple_connections=True,
    )
    column_name: Optional[str] = InputField(
        agent_description=(
            "Choose the assigned field name. An existing field is replaced, with only a warning; "
            "use a new name if the original must be retained."
        ),
        description="Имя новой колонки",
    )

    column_bindings: list[ColumnBinding] | None = InputField(
        default=None, description="Source Series name to target column name."
    )
    overwrite_existing: bool = InputField(default=False)
    output: dd.DataFrame = OutputField()

    @classmethod
    def runtime_inputs(cls, inputs):
        return contract_runtime_inputs(inputs, ("column_name",), ("column_bindings",))

    def _bound_columns(self):
        series_list = self.column_data if isinstance(self.column_data, list) else [self.column_data]
        sources = {}
        for series in series_list:
            if not isinstance(series, dd.Series):
                raise NodeValidationError("Every connected value must be a Dask Series.")
            if series.name in sources:
                raise NodeValidationError(f"Duplicate source Series name '{series.name}'.")
            sources[series.name] = series
        if not self.column_bindings:
            raise NodeValidationError("Add at least one column binding.")
        result = {}
        for raw in self.column_bindings:
            binding = ColumnBinding.model_validate(resolve_input_bindings(self, raw))
            if binding.source is None:
                if len(series_list) != 1:
                    raise NodeValidationError("An automatic binding requires exactly one Series.")
                source = series_list[0]
            elif binding.source not in sources:
                raise NodeValidationError(f"Source Series '{binding.source}' not connected.")
            else:
                source = sources[binding.source]
            if binding.target in result:
                raise NodeValidationError(f"Duplicate target '{binding.target}'.")
            if binding.target in self.df.columns and not self.overwrite_existing:
                raise NodeValidationError(f"Target '{binding.target}' already exists.")
            result[binding.target] = source
        return result

    @on_validation
    def check_input_column(self):
        if self.column_bindings is not None:
            self._bound_columns()
            return
        if not self.column_name or isinstance(self.column_data, list):
            raise NodeValidationError("Provide column_name for one Series or column_bindings.")
        if self.column_name in self.df.columns:
            logger.warning(f"Column {self.column_data} already exists in DataFrame")

    def process(self):
        if self.column_bindings is not None:
            self.output = self.df.assign(**self._bound_columns())
        else:
            self.output = self.df.assign(**{self.column_name: self.column_data})
