from typing import Literal

from dask import dataframe as dd

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.hooks import on_validation

FillNAFunction = Literal["mean", "median", "mode", "min", "max", "ffill", "bfill"]


class DataFrameFillNA(DFOutputBaseNode):
    TITLE = "Fill NA/Null Values"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField()
    # Словарь функций: {"column_name": "func", ...}
    fill_values: dict[str, FillNAFunction] = InputField()

    output: dd.DataFrame = OutputField()

    _ALLOWED_FUNCTIONS = frozenset({"mean", "median", "mode", "min", "max", "ffill", "bfill"})

    @on_validation
    def validate_fill_values(self):
        if not isinstance(self.fill_values, dict) or not self.fill_values:
            raise ValueError("fill_values must be a non-empty dictionary")

        missing_columns = [
            column for column in self.fill_values
            if column not in self.df.columns
        ]
        if missing_columns:
            raise ValueError(f"Columns not found in DataFrame: {missing_columns}")

        invalid_functions = [
            function_name for function_name in self.fill_values.values()
            if function_name not in self._ALLOWED_FUNCTIONS
        ]
        if invalid_functions:
            raise ValueError(f"Unsupported fill NA functions: {invalid_functions}")

    @staticmethod
    def _fill_value(series: dd.Series, function_name: FillNAFunction):
        if function_name == "mode":
            return series.dropna().value_counts().idxmax()
        return getattr(series, function_name)()

    def process(self):
        logger.info(f"Filling NA values: {self.fill_values}")
        result = self.df.copy()

        for column, function_name in self.fill_values.items():
            series = result[column]
            if function_name == "ffill":
                result[column] = series.ffill()
                continue
            if function_name == "bfill":
                result[column] = series.bfill()
                continue
            result[column] = series.fillna(self._fill_value(series, function_name))

        self.output = result
