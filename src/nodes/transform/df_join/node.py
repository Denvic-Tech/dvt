from typing import List, Literal, Optional

from dask import dataframe as dd

from core.utils import get_useful_indexes, is_internal_dvt_name
from core.utils.dataframe_index import get_physical_index

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO


class DataFrameJoin(DFOutputBaseNode):
    TITLE = "Join DataFrames"
    ICON_KEY = "join-tables"
    EMOJI = "🔗"
    CATEGORY = "Transform"

    left: dd.DataFrame = InputField(
        agent_description=(
            "Connect the left table and inspect its keys, nulls and duplicate frequencies. For a "
            "left join this is the preserved side; estimate row multiplication before joining "
            "large tables."
        ),
    )
    right: dd.DataFrame = InputField(
        agent_description=(
            "Connect the right table and inspect key cardinality against the left side. "
            "Conflicting non-key names receive a _right suffix; verify the resulting names before "
            "downstream selection."
        ),
    )

    left_on: Optional[List[IO.COLUMN_NAME]] = InputField(
        agent_description=(
            "Choose exact left-side key names with compatible types and the same positional "
            "meaning as right_on. Explicitly select keys for ordinary joins; omitted keys can "
            "invoke index-based behavior. Keys do not restrict a cross join."
        ),description="Колонки для join в левом DF",
                                               metadata_source_field="left")
    right_on: Optional[List[IO.COLUMN_NAME]] = InputField(
        agent_description=(
            "Match each right key position to left_on and verify types, nulls and repeated values. "
            "A non-unique key can multiply rows; this node does not deduplicate either side."
        ),description="Колонки для join в правом DF",
                                                metadata_source_field="right")

    how: Literal["left", "right", "outer", "inner", "cross"] = InputField(
        agent_description=(
            "Choose which unmatched rows must survive. The default left join preserves left-side "
            "records; inner drops unmatched rows. Use cross only for an intended Cartesian product "
            "after estimating left_rows * right_rows."
        ),
        default="left",
    )

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

    @staticmethod
    def _for_column_merge(df: dd.DataFrame) -> dd.DataFrame:
        name = df.index.name
        if name in df.columns:
            return df.reset_index(drop=True)
        if get_useful_indexes(df):
            return df.reset_index()
        return df

    @staticmethod
    def _has_bound_index(df: dd.DataFrame, key: str) -> bool:
        index = get_physical_index(df)
        return (
            index is not None
            and index.bound_column == key
            and df.known_divisions
            and key in df.columns
            and df.index.dtype == df.dtypes[key]
        )

    @staticmethod
    def _use_business_index(df: dd.DataFrame, keys: list[str] | None) -> bool:
        if is_internal_dvt_name(df.index.name):
            return False
        indexes = get_useful_indexes(df)
        return indexes == (keys or []) and all(name not in df.columns for name in indexes)

    def process(self):
        df1 = self.left
        df2 = self.right

        left_on = self._normalize_join_keys(self.left_on)
        right_on = self._normalize_join_keys(self.right_on)

        if self.how == "cross":
            df1 = self._for_column_merge(df1)
            df2 = self._for_column_merge(df2)

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
            if left_on and len(left_on) == 1 and left_on == right_on:
                key = left_on[0]
                if (
                    self._has_bound_index(df1, key)
                    and self._has_bound_index(df2, key)
                    and df1.index.dtype == df2.index.dtype
                ):
                    df2, _ = self._rename_conflicting_right_columns(df1, df2, left_on, right_on)
                    columns = [*df1.columns, *(name for name in df2.columns if name != key)]
                    merged = dd.merge(
                        df1.drop(columns=key),
                        df2.drop(columns=key),
                        how=self.how,
                        left_index=True,
                        right_index=True,
                        suffixes=("", ""),
                    )
                    self.output = self._drop_internal_columns(
                        merged.assign(**{key: merged.index})[columns]
                    )
                    return

            can_merge_by_left_index = self._use_business_index(df1, left_on)
            can_merge_by_right_index = self._use_business_index(df2, right_on)
            if not left_on and not right_on and not (
                can_merge_by_left_index and can_merge_by_right_index
            ) and any(is_internal_dvt_name(df.index.name) for df in (df1, df2)):
                can_merge_by_left_index = can_merge_by_right_index = False
                left_on = right_on = [name for name in df1.columns if name in df2.columns]

            if not can_merge_by_left_index:
                df1 = self._for_column_merge(df1)
            if not can_merge_by_right_index:
                df2 = self._for_column_merge(df2)

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
                left_on=None if can_merge_by_left_index else left_on or None,
                right_on=None if can_merge_by_right_index else right_on or None,
                left_index=can_merge_by_left_index,
                right_index=can_merge_by_right_index,
                suffixes=("", ""),
            )

        self.output = self._drop_internal_columns(merged)
