from dask import dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField, NodeValidationError
from src.node_dsl.hooks import on_validation
from src.node_dsl.node_typing import IO


class FillColumnNullValues(DFOutputBaseNode):
    TITLE = "Fill empty values in column"
    CATEGORY = "Transform"
    EXPERIMENTAL = True

    TAGS = ["Unstable"]

    column_with_null: dd.Series = InputField()
    column_with_values: dd.Series = InputField(description="Данные колонки")

    output: IO.COLUMN = OutputField()

    @on_validation
    def check_columns_len(self):
        if len(self.column_with_values) != len(self.column_with_null):
            raise NodeValidationError("Column sizes not equal")

    def process(self):
        self.output = self.column_with_null.copy()
        self.output = self.output.fillna(value=self.column_with_values)
