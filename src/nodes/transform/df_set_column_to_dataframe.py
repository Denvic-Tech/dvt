from dask import dataframe as dd

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.hooks import on_validation
from src.node_dsl.node_typing import IO


class SetColumnToDataFrame(DFOutputBaseNode):
    TITLE = "Add column to DataFrame"
    CATEGORY = "Transform"
    EXPERIMENTAL = True
    TAGS = ["Unstable"]

    df: dd.DataFrame = InputField()
    column_data: IO.COLUMN = InputField(description="Данные колонки")
    column_name: str = InputField(description="Имя новой колонки")

    output: dd.DataFrame = OutputField()

    @on_validation
    def check_input_column(self):
        if self.column_name in self.df.columns:
            logger.warning(f"Column {self.column_data} already exists in DataFrame")

    def process(self):
        self.output = self.df.assign(**{self.column_name: self.column_data})
