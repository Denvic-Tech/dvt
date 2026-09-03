from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Literal, cast

from dask import dataframe as dd
import numpy as np
import pandas as pd
from pandas.api import types as pd_types

from core.types import DataType

from src.node_dsl import BaseNode, InputField, OutputField, NodeValidationError
from src.node_dsl.hooks import on_validation
from src.node_dsl.node_typing import IO
from src.node_dsl.variables import VariableOutput, make_unresolved_value
from src.node_dsl.variables.type_system import (
    infer_variable_scalar_type_from_data_type,
    infer_variable_scalar_type_from_value,
)

AggregationFunction = Literal[
    "first",
    "last",
    "min",
    "max",
    "sum",
    "mean",
    "count",
    "nunique",
    "std",
    "var",
]


@dataclass
class SelectedVariable:
    source_column_name: str
    agg_func: AggregationFunction


def normalize_selected_variable(
        variable_name: str,
        item: SelectedVariable | dict,
) -> SelectedVariable:
    if isinstance(item, dict):
        try:
            item = SelectedVariable(**item)
        except TypeError as exc:
            raise NodeValidationError(
                f"Некорректная конфигурация переменной '{variable_name}': {exc}"
            ) from exc

    if not isinstance(item, SelectedVariable):
        raise NodeValidationError(
            f"Переменная '{variable_name}' должна быть объектом SelectedVariable или dict."
        )

    return item


def _is_missing_value(value: Any) -> bool:
    if value is None or value is pd.NaT:
        return True

    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _infer_variable_type_from_value(value: Any) -> IO | None:
    if _is_missing_value(value):
        return None

    return infer_variable_scalar_type_from_value(normalize_variable_value(value))


def _infer_variable_type_from_dtype(source_dtype: Any, agg_func: AggregationFunction) -> IO:
    if agg_func in {"count", "nunique"}:
        return IO.INT

    if agg_func in {"mean", "std", "var"} and not pd_types.is_timedelta64_dtype(source_dtype):
        return IO.FLOAT

    inferred_type = infer_variable_scalar_type_from_data_type(DataType.from_type(source_dtype))
    return inferred_type or IO.STRING


def infer_variable_type(value: Any, source_dtype: Any, agg_func: AggregationFunction) -> IO:
    return _infer_variable_type_from_value(value) or _infer_variable_type_from_dtype(
        source_dtype=source_dtype,
        agg_func=agg_func,
    )


def normalize_variable_value(value: Any) -> Any:
    if _is_missing_value(value):
        return None

    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, pd.Timedelta):
        return value.to_pytimedelta()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)

    return value


class DataFrameSelectVariables(BaseNode):
    TITLE = "Select Variables From DataFrame"
    EMOJI = "☑️"
    CATEGORY = "Transform"
    CACHABLE = False

    df: dd.DataFrame = InputField()

    selected_variables: Dict[str, SelectedVariable] = InputField(
        default={},
        description="Переменные, выбранные из DataFrame",
        use_connection=False,
    )

    output_variables: Dict[str, IO.VARIABLE] = OutputField(
        description="Output variables",
        force_handle_visible=True,
    )

    def _normalize_selected_variables(self) -> Dict[str, SelectedVariable]:
        raw_selected_variables = self.selected_variables or {}
        if not isinstance(raw_selected_variables, dict):
            raise NodeValidationError("`selected_variables` должен быть словарем.")

        return {
            variable_name: normalize_selected_variable(variable_name, selected_variable)
            for variable_name, selected_variable in raw_selected_variables.items()
        }

    def _validate_required_columns(self, normalized_selected_variables: Dict[str, SelectedVariable]) -> None:
        required_columns = {
            item.source_column_name
            for item in normalized_selected_variables.values()
        }
        missing_columns = required_columns - set(self.df.columns)
        if missing_columns:
            raise NodeValidationError(
                f"В DataFrame не хватает колонок: {sorted(missing_columns)}"
            )

    @on_validation
    def validate_selected_variables(self):
        normalized_selected_variables = self._normalize_selected_variables()
        self._validate_required_columns(normalized_selected_variables)
        self.selected_variables = normalized_selected_variables

    @staticmethod
    def _aggregate_series(series: dd.Series, agg_func: AggregationFunction) -> Any:
        if agg_func == "first":
            result = series.head(1)
            return None if result.empty else result.iloc[0]

        if agg_func == "last":
            result = series.tail(1)
            return None if result.empty else result.iloc[0]

        aggregation = getattr(series, agg_func, None)
        if aggregation is None or not callable(aggregation):
            raise NodeValidationError(f"Неподдерживаемая функция агрегации: {agg_func}")

        result = cast(Any, aggregation())
        return result.compute()

    def process(self):
        normalized_selected_variables = self._normalize_selected_variables()
        self._validate_required_columns(normalized_selected_variables)
        self.selected_variables = normalized_selected_variables

        if not normalized_selected_variables:
            return

        next_output_variables = dict(self.output_variables or {})
        df_dtypes = self.df.dtypes.to_dict()
        aggregated_values: dict[tuple[str, AggregationFunction], Any] = {}

        for variable_name, selected_variable in normalized_selected_variables.items():
            cache_key = (selected_variable.source_column_name, selected_variable.agg_func)
            if cache_key not in aggregated_values:
                aggregated_values[cache_key] = self._aggregate_series(
                    self.df[selected_variable.source_column_name],
                    selected_variable.agg_func,
                )

            raw_value = aggregated_values[cache_key]
            variable_type = infer_variable_type(
                value=raw_value,
                source_dtype=df_dtypes[selected_variable.source_column_name],
                agg_func=selected_variable.agg_func,
            )
            next_output_variables[variable_name] = VariableOutput(
                name=variable_name,
                type=variable_type,
                value=normalize_variable_value(raw_value),
                var_type="user",
            )

        # self.df.compute()
        self.output_variables = next_output_variables

    def process_metadata(self) -> None:
        normalized_selected_variables = self._normalize_selected_variables()
        self._validate_required_columns(normalized_selected_variables)
        self.selected_variables = normalized_selected_variables

        if not normalized_selected_variables:
            return

        next_output_variables = dict(self.output_variables or {})
        df_dtypes = self.df.dtypes.to_dict()

        for variable_name, selected_variable in normalized_selected_variables.items():
            variable_type = _infer_variable_type_from_dtype(
                source_dtype=df_dtypes[selected_variable.source_column_name],
                agg_func=selected_variable.agg_func,
            )
            next_output_variables[variable_name] = VariableOutput(
                name=variable_name,
                type=variable_type,
                value=make_unresolved_value(
                    reason=(
                        f"Value is not available in metadata mode for "
                        f"{selected_variable.source_column_name}.{selected_variable.agg_func}."
                    ),
                    declared_type=variable_type,
                ),
                var_type="user",
            )

        self.output_variables = next_output_variables
