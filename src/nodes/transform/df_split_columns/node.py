from dask import dataframe as dd
import pandas as pd
import numpy as np

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO


class DataFrameSplitColumn(DFOutputBaseNode):
    TITLE = "Split Column"
    ICON_KEY = "dataframe-split-column"
    EMOJI = "✂️"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField(
        agent_description=(
            "Check row count, target values and existing names before splitting. The operation "
            "adds columns while preserving rows and alignment within each partition."
        ),
    )
    column: IO.COLUMN_NAME = InputField(
        agent_description=(
            "Select the existing field to split. Values are converted to strings first; inspect "
            "how source nulls appear after stringification."
        ),
    )
    delimiter: str = InputField(
        agent_description=(
            "Choose the separator from real values and account for pandas str.split pattern "
            "semantics for multi-character delimiters. Test separators containing regex "
            "metacharacters instead of assuming literal matching."
        ),
    )
    max_splits: int = InputField(
        agent_description=(
            "Set the maximum split count n, producing exactly n+1 columns named source_1 through "
            "source_(n+1). Check the largest required split and collisions with existing names; "
            "missing pieces are filled with NaN."
        ),
        default=1,
        min_value=1,
        description="Maximum number of splits (n). Produces n+1 columns."
    )
    drop_source: bool = InputField(
        agent_description=(
            "Enable only when downstream nodes no longer need the original field. The default "
            "retains it alongside all generated split columns."
        ),
        default=False,
    )

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
