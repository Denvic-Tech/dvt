from typing import Dict, List, Literal, Optional, Sequence

import pandas as pd
from dask import dataframe as dd

from src.logger import logger
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.node_typing import IO


class DataFramePivot(DFOutputBaseNode):
    TITLE = "Pivot DataFrame (Wide Format)"
    EMOJI = "🧩"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField()

    index: IO.COLUMN_NAME = InputField(
        description="Колонка, значения которой станут строками сводной таблицы."
    )
    column: IO.COLUMN_NAME = InputField(
        description="Колонка, уникальные значения которой станут столбцами."
    )

    aggfunc: Dict[str, Literal["mean", "sum", "count", "first", "last"]] = InputField(
        description="Словарь {<колонка>: <функция>}, например: {'sales':'sum','revenue':'mean'}."
    )

    output: dd.DataFrame = OutputField()

    _ALLOWED_FUNCS = {"mean", "sum", "count", "first", "last"}

    # ---------- helpers ----------

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

    def _validate_value_columns(self, df: dd.DataFrame, cols: Sequence[str]):
        """Для value-колонок требуем именно наличие в df.columns (индекс сюда не подходит)."""
        col_set = set(map(str, df.columns))
        missing = [c for c in cols if c not in col_set]
        if missing:
            raise KeyError(f"Value columns not found in DataFrame columns: {missing}")

    def _ensure_index_fields_are_columns(self, df: dd.DataFrame, *names: str) -> dd.DataFrame:
        """
        Если index/column выбраны из имён индекса, сбрасываем индекс в колонки один раз.
        """
        names = [n for n in names if n]
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

    def _extract_values_from_aggfunc(self) -> List[str]:
        """
        Единственный источник списка метрик — ключи aggfunc.
        """
        if not self.aggfunc or len(self.aggfunc) == 0:
            raise ValueError(
                "aggfunc обязателен и должен содержать хотя бы одну пару {колонка: функция}."
            )
        return list(self.aggfunc.keys())

    def _validate_and_normalize_agg_map(self, values: List[str]) -> Dict[str, str]:
        """
        Проверяем, что для каждой value-колонки задана допустимая функция.
        (Лишних ключей быть не может, так как values = aggfunc.keys()).
        """
        assert self.aggfunc is not None
        agg_map: Dict[str, str] = {}

        for v in values:
            func = self.aggfunc.get(v)
            if func not in self._ALLOWED_FUNCS:
                raise ValueError(
                    f"Unsupported aggfunc '{func}' для колонки '{v}'. "
                    f"Разрешено: {sorted(self._ALLOWED_FUNCS)}"
                )
            agg_map[v] = func

        return agg_map

    def _categorize_columns_axis(self, df: dd.DataFrame, col: str) -> dd.DataFrame:
        """
        Dask требует category dtype для 'columns' в pivot_table.
        Приводим к string и делаем categorize, чтобы категории были known.
        """
        try:
            if isinstance(df._meta[col].dtype, pd.CategoricalDtype):
                return df
        except Exception:
            pass

        df2 = df.assign(**{col: df[col].astype("string")})
        df2 = df2.categorize(columns=[col])
        return df2

    def _flatten_columns_strict(self, df: dd.DataFrame) -> dd.DataFrame:
        """
        Убираем MultiIndex, сохраняя значения pivot-колонки без префикса.

        Если несколько value-колонок создают одинаковое имя, короткое имя получает
        первая колонка из aggfunc, а остальные получают префикс value-колонки.
        """
        flat_columns = self._build_flat_column_names(df.columns)

        meta = df._meta.copy()
        meta.columns = flat_columns

        def _apply(pdf):
            pdf = pdf.copy()
            pdf.columns = flat_columns
            return pdf

        return df.map_partitions(_apply, meta=meta)

    def _build_flat_column_names(self, columns: Sequence[object]) -> list[str]:
        value_priority = {
            str(value_column): position
            for position, value_column in enumerate(self._extract_values_from_aggfunc())
        }
        fallback_priority = len(value_priority)
        descriptors = []

        for position, column in enumerate(columns):
            if isinstance(column, tuple):
                parts = [str(part) for part in column if part not in (None, "")]
            else:
                parts = [str(column)]

            base_name = parts[-1] if parts else ""
            value_name = parts[0] if len(parts) > 1 else None
            descriptors.append((position, parts, base_name, value_name))

        owner_by_base: dict[str, int] = {}
        for position, _, base_name, value_name in descriptors:
            current_owner = owner_by_base.get(base_name)
            if current_owner is None:
                owner_by_base[base_name] = position
                continue

            current_value_name = descriptors[current_owner][3]
            current_rank = value_priority.get(current_value_name, fallback_priority)
            candidate_rank = value_priority.get(value_name, fallback_priority)
            if candidate_rank < current_rank:
                owner_by_base[base_name] = position

        result: list[str | None] = [None] * len(descriptors)
        used_names = set(owner_by_base)

        for base_name, owner_position in owner_by_base.items():
            result[owner_position] = base_name

        duplicates = [
            descriptor
            for descriptor in descriptors
            if owner_by_base[descriptor[2]] != descriptor[0]
        ]
        duplicates.sort(
            key=lambda descriptor: (
                value_priority.get(descriptor[3], fallback_priority),
                descriptor[0],
            )
        )

        for position, parts, base_name, _ in duplicates:
            candidate = "_".join(parts) if len(parts) > 1 else base_name
            unique_name = candidate
            suffix = 2
            while unique_name in used_names:
                unique_name = f"{candidate}_{suffix}"
                suffix += 1
            result[position] = unique_name
            used_names.add(unique_name)

        return [name if name is not None else "" for name in result]

    def process(self):
        if self.df is None:
            raise ValueError("Input dataframe is None")

        idx = self.index
        col = self.column

        if not idx or not col:
            raise ValueError("Both 'index' and 'column' must be provided.")
        if idx == col:
            raise ValueError("Parameters 'index' and 'column' must be different.")

        df_work = self._ensure_index_fields_are_columns(self.df, idx, col)

        self._validate_presence(df_work, [idx], "Index columns")
        self._validate_presence(df_work, [col], "Columns for pivot")

        values = self._extract_values_from_aggfunc()
        self._validate_value_columns(df_work, values)

        agg_map = self._validate_and_normalize_agg_map(values)

        df_work = self._categorize_columns_axis(df_work, col)

        funcs = sorted({agg_map[v] for v in values})
        parts: List[dd.DataFrame] = []

        logger.info(f"Pivot per aggfunc groups: {funcs}")
        for f in funcs:
            vals_f = [v for v in values if agg_map[v] == f]
            if not vals_f:
                continue
            logger.info(f"  - aggfunc={f}, values={vals_f}")
            try:
                part = df_work.pivot_table(
                    index=idx,
                    columns=col,
                    values=vals_f,
                    aggfunc=f
                )
            except Exception as e:
                logger.error(f"Error pivoting with aggfunc='{f}' and values={vals_f}: {e}")
                raise
            parts.append(part)

        if not parts:
            raise ValueError("No pivot results produced (empty aggfunc?).")

        out = parts[0] if len(parts) == 1 else dd.concat(parts, axis=1)

        out = self._flatten_columns_strict(out)

        self.output = out
        logger.info("Pivot completed.")
