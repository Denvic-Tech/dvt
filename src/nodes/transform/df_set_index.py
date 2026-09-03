import pandas as pd
from dask import dataframe as dd

from core.utils import get_useful_indexes

from src.node_dsl import DFOutputBaseNode, InputField, OutputField, NodeValidationError
from src.node_dsl.node_typing import IO


def _check_on_nulls(
        pdf: pd.DataFrame,
        *,
        col: str,
        partition_info: dict = None
) -> pd.DataFrame:
    if pdf[col].isnull().any():
        raise NodeValidationError(f"Column '{col}' contains null values, cannot set as index.")
    return pdf


_check_on_nulls.__dask_tokenize__ = lambda *args, **kwargs: (*args, tuple(sorted(kwargs.items())))


class DataFrameSetIndex(DFOutputBaseNode):
    TITLE = "DataFrame Set Index"
    CATEGORY = "Transform"
    EXPERIMENTAL = True
    TAGS = ["Unstable", "Not tested"]

    df: dd.DataFrame = InputField()
    index_col: IO.COLUMN_NAME = InputField(description="Колонки для индекса в DF")

    output: dd.DataFrame = OutputField()

    async def _get_cached_df_and_skip(self, df_meta=None, index=None) -> bool:
        return await super()._get_cached_df_and_skip(df_meta=df_meta, index=self.index_col)

    def process(self):
        df = self.df

        useful_indexes = get_useful_indexes(df)
        if useful_indexes:
            df = df.reset_index()

        df = df.map_partitions(
            _check_on_nulls,
            col=self.index_col,
            meta=df._meta
        )

        self.output = df.set_index(self.index_col,
                                   partition_size=128 * 1024 * 1024,
                                   shuffle="tasks")
