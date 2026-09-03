from typing import Hashable, List, Literal, Optional

from dask import dataframe as dd
from dask import delayed
import pandas as pd

from src.node_dsl.node_typing import IO
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.hooks import on_validation
from src.node_dsl.exceptions import NodeValidationError
from src.logger import logger


class DataFrameGroupByAgg(DFOutputBaseNode):
    TITLE = "GroupBy + Aggregation"
    EMOJI = "📊"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField()
    group_by_columns: List[IO.COLUMN_NAME] = InputField(default=[])

    new_cols: Optional[List[str]] = InputField(
        description="List of new column names for the aggregated results."
    )
    source_cols: Optional[List[IO.COLUMN_NAME]] = InputField(
        description="List of columns to aggregate.",
    )
    agg_funcs: Optional[List[
        Literal["sum", "mean", "min", "max", "count", "first", "last", "nunique", "std", "var"]
    ]] = InputField(
        description="List of aggregation functions to apply to each column.",
    )

    output: dd.DataFrame = OutputField()

    @on_validation
    def validate_agg(self) -> None:
        if not self.group_by_columns and not self.new_cols and not self.source_cols and not self.agg_funcs:
            raise NodeValidationError(
                "Either 'group_by_columns' or aggregation fields must be provided. "
                "Global aggregation requires 'new_cols', 'source_cols' and 'agg_funcs'."
            )

        # Разрешаем пустые агрегации
        if not self.new_cols and not self.source_cols and not self.agg_funcs:
            return  # Без агрегаций - всё ок

        # Если есть хоть одно поле агрегации, проверяем все
        if not (self.new_cols and self.source_cols and self.agg_funcs):
            raise NodeValidationError(
                "All aggregation fields ('new_cols', 'source_cols', 'agg_funcs') "
                "must be provided together or all left empty."
            )

        # Проверяем длины
        if not (len(self.new_cols) == len(self.source_cols) == len(self.agg_funcs)):
            raise NodeValidationError(
                f"Length of 'new_cols' ({len(self.new_cols)}), 'source_cols' ({len(self.source_cols)}) "
                f"and 'agg_funcs' ({len(self.agg_funcs)}) must be the same."
            )

    @staticmethod
    def _make_unique_index_level_names(meta_df: pd.DataFrame) -> list[Hashable]:
        index = meta_df.index
        if isinstance(index, pd.MultiIndex):
            raw_names = [(name if name is not None else f"level_{i}") for i, name in enumerate(index.names)]
        else:
            raw_names = [index.name if index.name is not None else "index"]

        existing = set(meta_df.columns.tolist())
        resolved: list[Hashable] = []
        for name in raw_names:
            if name not in existing and name not in resolved:
                resolved.append(name)
                existing.add(name)
                continue

            base = f"__index__{name}"
            candidate: Hashable = base
            suffix = 1
            while candidate in existing or candidate in resolved:
                suffix += 1
                candidate = f"{base}_{suffix}"

            resolved.append(candidate)
            existing.add(candidate)

        return resolved

    @classmethod
    def _reset_index_safely(cls, ddf: dd.DataFrame) -> dd.DataFrame:
        meta = ddf._meta
        names = cls._make_unique_index_level_names(meta)
        names_param: Hashable | list[Hashable] = names if isinstance(meta.index, pd.MultiIndex) else names[0]

        # TODO: Рассмотреть стратегию "колонка только в индексе, без дублирования в df.columns".
        # Для этого потребуется адаптировать ноды, которые сейчас ожидают такие поля именно в columns.
        meta_reset = meta.reset_index(allow_duplicates=True, names=names_param)
        return ddf.map_partitions(
            lambda pdf: pdf.reset_index(allow_duplicates=True, names=names_param),
            meta=meta_reset,
        )

    @staticmethod
    def _build_global_scalar(ddf: dd.DataFrame, source_col: str, agg_func: str):
        series = ddf[source_col]
        if agg_func == "nunique":
            return series.nunique()
        if agg_func == "first":
            return delayed(DataFrameGroupByAgg._first_from_series_partitions)(series.to_delayed())
        if agg_func == "last":
            return delayed(DataFrameGroupByAgg._last_from_series_partitions)(series.to_delayed())
        return getattr(series, agg_func)()

    @staticmethod
    def _first_from_series_partitions(partitions: list[pd.Series]):
        for partition in partitions:
            non_null = partition.dropna()
            if not non_null.empty:
                return non_null.iloc[0]
        return None

    @staticmethod
    def _last_from_series_partitions(partitions: list[pd.Series]):
        for partition in reversed(partitions):
            non_null = partition.dropna()
            if not non_null.empty:
                return non_null.iloc[-1]
        return None

    @staticmethod
    def _global_agg_meta_dtype(source_series: dd.Series, agg_func: str) -> str | object:
        if agg_func in {"count", "nunique"}:
            return "int64"
        if agg_func in {"mean", "std", "var"}:
            return "float64"
        return source_series._meta.dtype

    @staticmethod
    def _build_global_agg_row(new_cols: list[str], dtype_map: dict[str, object], *values) -> pd.DataFrame:
        row = pd.DataFrame([dict(zip(new_cols, values))], columns=new_cols)
        return row.astype(dtype_map)

    @classmethod
    def _build_global_aggregation_output(cls, ddf: dd.DataFrame, new_cols, source_cols, agg_funcs) -> dd.DataFrame:
        scalar_values = []
        meta_dict: dict[str, pd.Series] = {}
        for new_col, source_col, agg_func in zip(new_cols, source_cols, agg_funcs):
            scalar_values.append(cls._build_global_scalar(ddf, source_col, agg_func))
            meta_dict[new_col] = pd.Series(dtype=cls._global_agg_meta_dtype(ddf[source_col], agg_func))

        meta = pd.DataFrame(meta_dict)
        row = delayed(cls._build_global_agg_row)(new_cols, meta.dtypes.to_dict(), *scalar_values)
        return dd.from_delayed([row], meta=meta)

    def process(self):
        # Если группировка не задана, выполняем глобальную агрегацию по всему DataFrame.
        if not self.group_by_columns:
            logger.info("No group by columns provided. Applying aggregation to the whole dataframe.")
            self.output = self._build_global_aggregation_output(
                self.df,
                self.new_cols,
                self.source_cols,
                self.agg_funcs,
            )
            logger.info("Successfully completed global aggregation.")
            return

        # Если агрегации не заданы - просто группируем
        if not self.new_cols or len(self.new_cols) == 0:
            logger.info(f"Performing GroupBy without aggregation on columns: {self.group_by_columns}")
            try:
                # Простая группировка - возвращаем уникальные группы
                df = self._reset_index_safely(self.df)
                result = df[self.group_by_columns].drop_duplicates()
                self.output = result
                logger.info(f"Successfully completed GroupBy (without aggregation).")
                return
            except Exception as e:
                logger.error(f"Error during simple GroupBy: {e}")
                raise

        # Оригинальная логика с агрегациями
        logger.info(f"Grouping by {self.group_by_columns} and named-aggregating")
        try:
            df = self._reset_index_safely(self.df)
            gb = df.groupby(self.group_by_columns, sort=False, dropna=False)

            parts = []
            for new_col, source_col, agg_func in zip(self.new_cols, self.source_cols, self.agg_funcs):
                if agg_func == "nunique":
                    s = gb[source_col].nunique()
                else:
                    s = gb[source_col].agg(agg_func)
                parts.append(s.rename(new_col).to_frame())

            if not parts:
                logger.warning("No aggregations computed. Returning original dataframe.")
                self.output = self.df
                return

            result = dd.concat(parts, axis=1)
            result = self._reset_index_safely(result)

            self.output = result
            logger.info(f"Successfully completed GroupBy aggregation.")

        except Exception as e:
            logger.error(f"Error during GroupBy aggregation: {e}")
            raise
