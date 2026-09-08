from typing import List

from dask import dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO
from src.logger import logger


class DataFrameSelectColumns(DFOutputBaseNode):
    TITLE = "Select Columns"
    EMOJI = "☑️"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField()
    columns: List[IO.COLUMN_NAME] = InputField()  # Список колонок для выбора

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
