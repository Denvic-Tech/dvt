from dask import dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField, NodeValidationError
from src.node_dsl.hooks import on_validation
from src.node_dsl.node_typing import IO


class FillColumnNullValues(DFOutputBaseNode):
    TITLE = "Fill empty values in column"
    CATEGORY = "Transform"
    EXPERIMENTAL = True

    TAGS = ["Unstable"]

    column_with_null: dd.Series = InputField(
        agent_description=(
            "Experimental column-level operation: connect the Series whose missing values should "
            "be replaced. Confirm both inputs have compatible indexes and types; length validation "
            "can compute the inputs."
        ),
    )
    column_with_values: dd.Series = InputField(
        agent_description=(
            "Connect fallback values aligned to the first Series index and of equal length. Equal "
            "row counts do not prove row correspondence; mismatched indexes can leave gaps or "
            "replace unintended rows."
        ),
        description="Данные колонки",
    )

    output: IO.COLUMN = OutputField()

    @on_validation
    def check_columns_len(self):
        if len(self.column_with_values) != len(self.column_with_null):
            raise NodeValidationError("Column sizes not equal")

    def process(self):
        self.output = self.column_with_null.copy()
        self.output = self.output.fillna(value=self.column_with_values)
