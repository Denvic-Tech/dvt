from typing import List, Optional, Sequence

import pandas as pd
from dask import dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO
from src.logger import logger


class DataFrameUnpivot(DFOutputBaseNode):
    TITLE = "Unpivot DataFrame (Long Format)"
    EMOJI = "🔄"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField()

    index_columns: List[IO.COLUMN_NAME] = InputField(
        description="Колонки, которые должны остаться неизменными (идентификаторы строк)."
    )
    columns_to_long: Optional[List[IO.COLUMN_NAME]] = InputField(
        description="Колонки, которые нужно расплавить. Если не заданы — берутся все кроме id_vars."
    )
    new_column_name_with_names: str = InputField(
        default="variable",
        description="Имя новой колонки, содержащей имена исходных столбцов."
    )
    new_column_name_with_values: str = InputField(
        default="value",
        description="Имя новой колонки, содержащей значения исходных столбцов."
    )

    output: dd.DataFrame = OutputField()

    # ---------- helpers ----------

    def _ensure_index_fields_are_columns(self, df: dd.DataFrame, id_names: List[str]) -> dd.DataFrame:
        """
        Если index/column выбраны из имён индекса, сбрасываем индекс в колонки один раз.
        """
        names = [n for n in id_names if n]
        if not names:
            return df
        idx_names = set(n for n in self._get_index_names(df) if n is not None)
        need_reset = any((n in idx_names) and (n not in df.columns) for n in names)
        if not need_reset:
            return df
        try:
            return df.reset_index(drop=False)
        except TypeError:
            return df.reset_index()

    def _get_index_names(self, df: dd.DataFrame) -> List[Optional[str]]:
        idx = df._meta.index
        if isinstance(idx, pd.MultiIndex):
            return list(idx.names)
        return [idx.name]

    def _validate_presence(self, df: dd.DataFrame, cols: Sequence[str], title: str):
        """Проверка наличия имен либо среди колонок, либо среди имён индекса."""
        col_set = set(map(str, df.columns))
        idx_names = set(n for n in self._get_index_names(df) if n is not None)
        missing = [c for c in cols if c not in col_set and c not in idx_names]
        if missing:
            raise KeyError(f"{title} not found in DataFrame: {missing}")

    # ---------- main ----------

    def process(self):
        if self.df is None:
            raise ValueError("Input dataframe is None")

        df_work = self._ensure_index_fields_are_columns(self.df, self.index_columns)

        self._validate_presence(df_work, self.index_columns, "id_vars")

        if self.columns_to_long:
            self._validate_presence(df_work, self.columns_to_long, "value_vars")

        df_work = df_work.melt(id_vars=self.index_columns,
                               value_vars=self.columns_to_long,
                               var_name=self.new_column_name_with_names,
                               value_name=self.new_column_name_with_values)
        # Придется все приводить к string, чтобы при кешировании не было ошибки с mixed types расплавленных колонок
        df_work[self.new_column_name_with_values] = df_work[self.new_column_name_with_values].apply(lambda x: str(x) if pd.notnull(x) else None)
        df_work[self.new_column_name_with_names] = df_work[self.new_column_name_with_names].apply(lambda x: str(x) if pd.notnull(x) else None)

        self.output = df_work
        self.output = self.output
        logger.info("Unpivot completed.")
