from typing import List, Literal, Optional

from dask import dataframe as dd

from core.utils import get_useful_indexes, is_internal_dvt_name

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO


class DataFrameJoin(DFOutputBaseNode):
    TITLE = "Join DataFrames"
    EMOJI = "🔗"
    CATEGORY = "Transform"

    left: dd.DataFrame = InputField()
    right: dd.DataFrame = InputField()

    left_on: Optional[List[IO.COLUMN_NAME]] = InputField(description="Колонки для join в левом DF",
                                               metadata_source_field="left")
    right_on: Optional[List[IO.COLUMN_NAME]] = InputField(description="Колонки для join в правом DF",
                                                metadata_source_field="right")

    how: Literal["left", "right", "outer", "inner", "cross"] = InputField(default="left")

    output: dd.DataFrame = OutputField()

    @staticmethod
    def _drop_internal_columns(df: dd.DataFrame) -> dd.DataFrame:
        internal_columns = [column for column in df.columns if is_internal_dvt_name(column)]
        if not internal_columns:
            return df
        return df.drop(columns=internal_columns)

    @staticmethod
    def _normalize_join_keys(value: Optional[list[str] | str]) -> Optional[list[str]]:
        if value is None:
            return None
        if isinstance(value, str):
            return [value]
        return list(value)

    @staticmethod
    def _rename_conflicting_right_columns(
            left: dd.DataFrame,
            right: dd.DataFrame,
            left_on: Optional[list[str]],
            right_on: Optional[list[str]],
            suffix: str = "_right",
    ) -> tuple[dd.DataFrame, Optional[list[str]]]:
        left_cols = set(left.columns)
        right_cols = set(right.columns)

        left_keys = set(left_on or [])
        right_keys = set(right_on or [])

        # join-ключи не считаем конфликтом
        conflicts = (left_cols & right_cols) - left_keys - right_keys

        if not conflicts:
            return right, right_on

        right = DataFrameJoin._clear_invalid_partition_mapping_before_rename(right)
        rename_map = {
            col: f"{col}{suffix}"
            for col in conflicts
        }

        right = right.rename(columns=rename_map)

        # на всякий случай, если вдруг right_on попал в rename_map
        if right_on:
            right_on = [rename_map.get(col, col) for col in right_on]

        return right, right_on

    @staticmethod
    def _clear_invalid_partition_mapping_before_rename(right: dd.DataFrame) -> dd.DataFrame:
        try:
            mapping_columns = right.expr.unique_partition_mapping_columns_from_shuffle
        except Exception:
            return right

        has_invalid_mapping = any(
            column is None or (isinstance(column, tuple) and any(item is None for item in column))
            for column in mapping_columns
        )
        if not has_invalid_mapping:
            return right

        # Drop broken shuffle metadata before rename; data and schema stay unchanged.
        return right.map_partitions(lambda partition: partition, meta=right._meta)

    def process(self):
        df1 = self.left
        df2 = self.right

        left_on = self._normalize_join_keys(self.left_on)
        right_on = self._normalize_join_keys(self.right_on)

        df1_indexes = get_useful_indexes(df1)
        df2_indexes = get_useful_indexes(df2)

        if self.how == "cross":

            if df1_indexes:
                df1 = df1.reset_index()

            if df2_indexes:
                df2 = df2.reset_index()

            tmp = "__tmp_key"
            df1 = df1.assign(**{tmp: 1})
            df2 = df2.assign(**{tmp: 1})

            df2, _ = self._rename_conflicting_right_columns(
                left=df1,
                right=df2,
                left_on=[tmp],
                right_on=[tmp],
            )

            merged = df1.merge(
                df2,
                on=tmp,
                how="inner",
                suffixes=("", ""),
            ).drop(columns=[tmp])

        else:
            can_merge_by_left_index = df1_indexes == (left_on or [])
            can_merge_by_right_index = df2_indexes == (right_on or [])

            left_on = None if can_merge_by_left_index else left_on
            right_on = None if can_merge_by_right_index else right_on

            if df1_indexes and not can_merge_by_left_index:
                df1 = df1.reset_index()

            if df2_indexes and not can_merge_by_right_index:
                df2 = df2.reset_index()

            df2, right_on = self._rename_conflicting_right_columns(
                left=df1,
                right=df2,
                left_on=left_on,
                right_on=right_on,
                suffix="_right",
            )

            merged = dd.merge(
                df1,
                df2,
                how=self.how,
                left_on=left_on,
                right_on=right_on,
                left_index=can_merge_by_left_index,
                right_index=can_merge_by_right_index,
                suffixes=("", ""),
            )

        self.output = self._drop_internal_columns(merged)
