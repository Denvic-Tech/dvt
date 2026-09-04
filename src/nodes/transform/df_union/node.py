from typing import Dict, Hashable, Sequence

from dask import dataframe as dd
import pandas as pd

from core.utils import get_useful_indexes
from src.node_dsl import DFOutputBaseNode, InputField, OutputField


class DataFrameUnion(DFOutputBaseNode):
    TITLE = "Union DataFrames"
    EMOJI = "➕"
    CATEGORY = "Transform"

    df1: dd.DataFrame = InputField()
    df2: dd.DataFrame = InputField()
    column_mapping: Dict[str, str] = InputField()

    output: dd.DataFrame = OutputField()

    @staticmethod
    def _find_duplicate_labels(labels: Sequence[Hashable]) -> list[Hashable]:
        seen: set[Hashable] = set()
        dups: list[Hashable] = []
        for x in labels:
            if x in seen and x not in dups:
                dups.append(x)
            seen.add(x)
        return dups

    @staticmethod
    def _make_unique_index_level_names(meta_df: pd.DataFrame) -> list[Hashable]:
        """
        Возвращает безопасные имена для уровней индекса при reset_index():
        - сохраняем исходные имена, если они не конфликтуют с существующими колонками
        - при конфликте переименовываем индексные колонки в `__index__<name>[_N]`
        - для None-имен (в MultiIndex) используем pandas-дефолт `level_<i>`
        """
        idx = meta_df.index
        if isinstance(idx, pd.MultiIndex):
            raw_names: list[Hashable] = [
                (n if n is not None else f"level_{i}") for i, n in enumerate(idx.names)
            ]
        else:
            # Для одиночного индекса pandas обычно использует имя `index`, если index.name is None.
            raw_names = [idx.name if idx.name is not None else "index"]

        existing: set[Hashable] = set(meta_df.columns.tolist())
        result: list[Hashable] = []
        for n in raw_names:
            if n not in existing and n not in result:
                result.append(n)
                existing.add(n)
                continue

            base = f"__index__{n}"
            candidate: Hashable = base
            i = 1
            while candidate in existing or candidate in result:
                i += 1
                candidate = f"{base}_{i}"
            result.append(candidate)
            existing.add(candidate)

        return result

    @classmethod
    def _reset_index_safely(cls, ddf: dd.DataFrame) -> dd.DataFrame:
        """
        В dask.DataFrame.reset_index нет параметров `names/allow_duplicates`, из-за чего легко
        получить дубли колонок (например, index.name совпадает с уже существующей колонкой).
        Здесь делаем reset_index на pandas-партициях с безопасными именами индексных колонок.
        """
        meta = ddf._meta
        names = cls._make_unique_index_level_names(meta)
        names_param: Hashable | list[Hashable]
        if isinstance(meta.index, pd.MultiIndex):
            names_param = names
        else:
            names_param = names[0]

        meta_reset = meta.reset_index(allow_duplicates=True, names=names_param)
        dups = cls._find_duplicate_labels(meta_reset.columns.tolist())
        if dups:
            raise ValueError(
                "DataFrameUnion: после reset_index получились дублирующиеся колонки: "
                f"{dups}. Проверьте, что имена индексных уровней не конфликтуют с колонками."
            )

        return ddf.map_partitions(
            lambda pdf: pdf.reset_index(allow_duplicates=True, names=names_param),
            meta=meta_reset,
        )

    @classmethod
    def _validate_unique_columns(cls, ddf: dd.DataFrame, *, ctx: str) -> None:
        cols = ddf._meta.columns.tolist()
        dups = cls._find_duplicate_labels(cols)
        if dups:
            raise ValueError(f"DataFrameUnion: дублирующиеся имена колонок в {ctx}: {dups}.")

    @classmethod
    def _validate_rename_mapping(cls, cols: Sequence[Hashable], rename_mapping: dict[Hashable, Hashable]) -> None:
        # Проверяем финальные имена колонок после rename; если будут дубли - лучше упасть с понятной ошибкой.
        final_cols = [rename_mapping.get(c, c) for c in cols]
        dups = cls._find_duplicate_labels(final_cols)
        if dups:
            raise ValueError(
                "DataFrameUnion: column_mapping приводит к дублирующимся именам колонок после переименования: "
                f"{dups}. Исправьте mapping, чтобы итоговые имена были уникальными."
            )

    @staticmethod
    def _is_datetime_dtype(dtype: object) -> bool:
        return bool(pd.api.types.is_datetime64_any_dtype(dtype))

    @classmethod
    def _cast_datetime_series_to_ns_naive(cls, series: dd.Series, column_name: Hashable) -> dd.Series:
        parsed = dd.to_datetime(series, errors="coerce", utc=True)
        return parsed.map_partitions(
            lambda s: s.dt.tz_localize(None).astype("datetime64[ns]"),
            meta=(column_name, "datetime64[ns]"),
        )

    @classmethod
    def _normalize_common_datetime_columns(cls, df1: dd.DataFrame, df2: dd.DataFrame) -> tuple[dd.DataFrame, dd.DataFrame]:
        common_columns = set(df1._meta.columns).intersection(df2._meta.columns)
        for column_name in common_columns:
            dtype1 = df1._meta[column_name].dtype
            dtype2 = df2._meta[column_name].dtype

            if not (cls._is_datetime_dtype(dtype1) and cls._is_datetime_dtype(dtype2)):
                continue

            df1 = df1.assign(
                **{column_name: cls._cast_datetime_series_to_ns_naive(df1[column_name], column_name)}
            )
            df2 = df2.assign(
                **{column_name: cls._cast_datetime_series_to_ns_naive(df2[column_name], column_name)}
            )
        return df1, df2

    def process(self):
        # Сохраняем имена индексов до reset_index
        df1 = self.df1
        df2 = self.df2

        df1_indexes = get_useful_indexes(df1)
        df2_indexes = get_useful_indexes(df2)

        # Более надежная обработка маппинга
        safe_mapping = {}
        for left, right in (self.column_mapping or {}).items():
            if not isinstance(left, str) or not isinstance(right, str):
                continue

            left_clean = left.strip()
            right_clean = right.strip()

            if not left_clean or not right_clean:
                continue

            # Проверяем, существует ли правая колонка в df2
            # Сначала ищем точное совпадение
            if right_clean in df2.columns:
                safe_mapping[left_clean] = right_clean
            else:
                # Ищем совпадение без учета пробелов в начале/конце
                for col in df2.columns:
                    if col.strip() == right_clean:
                        safe_mapping[left_clean] = col  # Используем оригинальное имя
                        break

        rename_mapping = {r: l for l, r in safe_mapping.items()}

        if df1_indexes:
            df1 = self._reset_index_safely(df1)

        if df2_indexes:
            df2 = self._reset_index_safely(df2)

        # Валидация маппинга до применения: иначе pandas/dask падают внутри concat неочевидной ошибкой.
        if rename_mapping:
            self._validate_rename_mapping(df2._meta.columns.tolist(), rename_mapping)

        df2 = df2.rename(columns=rename_mapping)

        self._validate_unique_columns(df1, ctx="df1")
        self._validate_unique_columns(df2, ctx="df2 (после rename)")
        df1, df2 = self._normalize_common_datetime_columns(df1, df2)

        # Объединение
        self.output = dd.concat([df1, df2], ignore_index=True)
