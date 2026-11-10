from typing import List

from dask import dataframe as dd

from core.utils import INTERNAL_DVT_PARTITION_INDEX_NAME, is_internal_dvt_name
from core.utils.dataframe_index import available_index_name, carry_physical_index

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO


class DataFrameDropColumns(DFOutputBaseNode):
    TITLE = "Drop Columns"
    ICON_KEY = "dataframe-drop-columns"
    EMOJI = "🗑️"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField(
        agent_description=(
            "Connect the table after verifying which fields remain necessary downstream, including "
            "join keys and write mappings."
        ),
    )
    columns: List[IO.COLUMN_NAME] = InputField(
        agent_description=(
            "List exact business fields to remove. Missing columns are ignored, so check spelling; "
            "dropping a field also used as the physical index hides its business name but "
            "preserves the index/divisions."
        ),
    )  # Список колонок для удаления

    output: dd.DataFrame = OutputField()

    def process(self):
        logger.info(f"Dropping columns: {self.columns}")
        # errors='ignore' позволяет не падать, если колонка уже отсутствует
        result = self.df.drop(columns=self.columns, errors='ignore')

        # Legacy frames can expose a field as both a column and a named index. Hide its
        # old business identity after projection, while preserving the physical divisions.
        # Dask DataFrame currently has a single logical index level in this path.
        index_name = self.df.index.name
        if (
            index_name is not None
            and index_name in self.columns
            and not is_internal_dvt_name(index_name)
        ):
            result = result.rename_axis(
                available_index_name(INTERNAL_DVT_PARTITION_INDEX_NAME, result.columns)
            )

        self.output = carry_physical_index(self.df, result)
        logger.info(f"Columns after drop: {self.output.columns}")
