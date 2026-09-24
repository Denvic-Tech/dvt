from typing import List

from dask import dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO
from src.logger import logger


class DataFrameSelectColumns(DFOutputBaseNode):
    TITLE = "Select Columns"
    ICON_KEY = "dataframe-select-columns"
    EMOJI = "☑️"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField(
        agent_description=(
            "Inspect the actual upstream columns and named index before selecting. This is a "
            "downstream projection and does not reduce the amount already fetched by an upstream "
            "reader."
        ),
    )
    columns: List[IO.COLUMN_NAME] = InputField(
        agent_description=(
            "Provide an explicit non-empty list in the desired output order. Missing names and the "
            "named index are filtered out; verify output metadata instead of assuming every "
            "requested name survives. An empty list currently exits without producing an output, "
            "so do not use it to mean all columns."
        ),
    )  # Список колонок для выбора

    output: dd.DataFrame = OutputField()

    def process(self):
        logger.info(f"Selecting DataFrame columns: {self.columns}")
        try:
            if not self.columns:
                logger.debug(f"Columns is not selected, skipping")
                return

            df_columns = list(self.df.columns)
            df_index_names = [self.df.index.name]

            self.columns = [
                col for col in self.columns if col not in df_index_names and col in df_columns
            ]

            self.output = self.df[self.columns]
            logger.info(f"Selected columns result dtypes: {self.output.dtypes}")

        except KeyError as e:
            logger.error(f"One or more columns not found for selection: {e}")
            raise
