from typing import List

from dask import dataframe as dd

from core.utils import INTERNAL_DVT_PARTITION_INDEX_NAME, is_internal_dvt_name

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO


class DataFrameDropColumns(DFOutputBaseNode):
    TITLE = "Drop Columns"
    EMOJI = "🗑️"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField()
    columns: List[IO.COLUMN_NAME] = InputField()  # Список колонок для удаления

    output: dd.DataFrame = OutputField()

    def process(self):
        logger.info(f"Dropping columns: {self.columns}")
        # errors='ignore' позволяет не падать, если колонка уже отсутствует
        result = self.df.drop(columns=self.columns, errors='ignore')

        # Read DB V3 intentionally exposes partition_col both as an ordinary business column
        # and as the physical Dask index. Once the user explicitly drops that business field,
        # keep the physical index/divisions for performance but hide its old business identity.
        # Dask DataFrame currently has a single logical index level in this path.
        index_name = self.df.index.name
        if (
            index_name is not None
            and index_name in self.columns
            and not is_internal_dvt_name(index_name)
        ):
            result = result.rename_axis(INTERNAL_DVT_PARTITION_INDEX_NAME)

        self.output = result
        logger.info(f"Columns after drop: {self.output.columns}")
