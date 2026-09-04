from typing import List, Optional

from dask import dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO
from src.logger import logger


class DataFrameSortValues(DFOutputBaseNode):
    TITLE = "Sort Values"
    CATEGORY = "Transform"
    EXPERIMENTAL = True

    df: dd.DataFrame = InputField()
    by: List[IO.COLUMN_NAME] = InputField()  # Список колонок для сортировки
    ascending: Optional[List[bool]] = InputField()  # Список булевых значений

    output: dd.DataFrame = OutputField()

    def process(self):
        # Проверяем, что количество колонок и направлений сортировки совпадает, если ascending задан
        asc = self.ascending
        if asc is not None and len(self.by) != len(asc):
            logger.warning(
                f"Length of 'by' ({len(self.by)}) and 'ascending' ({len(asc)}) mismatch. Using default ascending order."
            )
            asc = None  # Используем порядок по умолчанию

        logger.info(f"Sorting DataFrame by columns: {self.by}")
        self.output = self.df.sort_values(by=self.by, ascending=asc if asc is not None else True)
        logger.info(f"Successfully sorted DataFrame")
