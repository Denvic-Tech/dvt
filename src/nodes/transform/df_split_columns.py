from dask import dataframe as dd
import pandas as pd
import numpy as np

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO


class DataFrameSplitColumn(DFOutputBaseNode):
    TITLE = "Split Column"
    EMOJI = "✂️"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField()
    column: IO.COLUMN_NAME = InputField()
    delimiter: str = InputField()
    max_splits: int = InputField(
        default=1,
        min_value=1,
        description="Maximum number of splits (n). Produces n+1 columns."
    )
    drop_source: bool = InputField(default=False)

    output: dd.DataFrame = OutputField()

    def _split_partition(self, pdf: pd.DataFrame) -> pd.DataFrame:
        """Split колонку в одной партиции и гарантируем все новые колонки"""
        split_df = pdf[self.column].astype(str).str.split(
            self.delimiter, n=self.max_splits, expand=True
        )

        # Гарантируем наличие всех колонок
        expected_indices = list(range(self.max_splits + 1))
        for i in expected_indices:
            if i not in split_df.columns:
                split_df[i] = np.nan

        split_df = split_df[expected_indices]

        # Переименовываем с нумерацией с 1
        split_df = split_df.rename(
            columns={i: f"{self.column}_{i+1}" for i in expected_indices}
        )

        if self.drop_source:
            pdf = pdf.drop(columns=[self.column])

        return pd.concat([pdf, split_df], axis=1)

    def process(self):
        # Создаём meta для Dask
        meta_dict = {col: self.df._meta[col].dtype for col in self.df._meta.columns}
        if self.drop_source:
            meta_dict.pop(self.column, None)
        for i in range(self.max_splits + 1):
            meta_dict[f"{self.column}_{i+1}"] = "object"

        meta = pd.DataFrame({col: pd.Series(dtype=dtype) for col, dtype in meta_dict.items()})

        # Применяем map_partitions
        self.output = self.df.map_partitions(
            self._split_partition,
            meta=meta
        )
