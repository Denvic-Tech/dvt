from typing import List

from dask import dataframe as dd

from core.utils.dataframe_index import carry_physical_index

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO


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
            "Provide an explicit non-empty list in the desired output order. Names absent from "
            "the columns, including index-only names, are skipped. Verify the output metadata. "
            "An empty list exits without producing an output, "
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

            columns = [col for col in self.columns if col in self.df.columns]
            self.output = carry_physical_index(self.df, self.df[columns])
            logger.info(f"Selected columns result dtypes: {self.output.dtypes}")

        except KeyError as e:
            logger.error(f"One or more columns not found for selection: {e}")
            raise
