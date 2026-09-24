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
    )
    column_name: str = InputField(
        agent_description=(
            "Choose the assigned field name. An existing field is replaced, with only a warning; "
            "use a new name if the original must be retained."
        ),
        description="Имя новой колонки",
    )

    output: dd.DataFrame = OutputField()

    @on_validation
    def check_input_column(self):
        if self.column_name in self.df.columns:
            logger.warning(f"Column {self.column_data} already exists in DataFrame")

    def process(self):
        self.output = self.df.assign(**{self.column_name: self.column_data})
