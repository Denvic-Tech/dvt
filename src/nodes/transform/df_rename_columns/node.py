from typing import Dict, Optional

from dask import dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.logger import logger


class DataFrameRenameColumns(DFOutputBaseNode):
    TITLE = "Rename Columns"
    EMOJI = "✏️"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField()
    # Словарь переименования: {"old_name": "new_name", ...}
    mapping: Optional[Dict[str, str]] = InputField(default=None)

    output: dd.DataFrame = OutputField()

    def process(self):
        if self.mapping is None:
            logger.warning("No mapping provided for renaming columns. Skipping renaming.")
            self.output = self.df
            return

        result = self.df

        index_name = result.index.name
        if index_name is not None and index_name in self.mapping:
            new_index_name = self.mapping[index_name]
            result = result.rename_axis(new_index_name)

        logger.info(f"Renaming columns: {self.mapping}")
        result = result.rename(columns=self.mapping)

        self.output = result
