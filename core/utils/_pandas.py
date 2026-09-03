import pandas as pd

from core.types import DataFrameLike

_INTERNAL_NAME_PREFIXES = ("__dvt_",)
INTERNAL_DVT_PARTITION_INDEX_NAME = "__dvt_partition_key"


def is_internal_dvt_name(name: object) -> bool:
    normalized = str(name).strip().lower()
    return any(normalized.startswith(prefix) for prefix in _INTERNAL_NAME_PREFIXES)


def get_meta_df(df: DataFrameLike) -> pd.DataFrame:
    """Возвращает pandas-мету: сам df если он pandas, либо df._meta для dask."""
    return df.head(0) if isinstance(df, pd.DataFrame) else df._meta


def is_default_range_index(meta_df: pd.DataFrame) -> bool:
    """Дефолтный индекс 0..N-1 без имени — игнорируем как «неосмысленный»."""
    return isinstance(meta_df.index, pd.RangeIndex) and meta_df.index.name is None


def iter_index_levels(meta_df: pd.DataFrame):
    """
    Итератор по уровням индекса:
    yield (level_name, level_dtype)
    Для одноуровневого индекса даём ровно один элемент.
    """
    index = meta_df.index

    # MultiIndex
    if isinstance(index, pd.MultiIndex):
        # имена уровней, если нет — пропускаем
        for i in range(index.nlevels):
            lvl_name = index.names[i]
            if lvl_name is None:
                continue

            # dtype уровня: берём из levels[i].dtype (в мета-DF это доступно без compute)
            lvl_dtype = index.levels[i].dtype
            yield lvl_name, lvl_dtype
        return

    # Обычный одноуровневый индекс
    if is_default_range_index(meta_df) or index.name is None:
        return  # ничего не добавляем

    # Именованный или не-RangeIndex — считаем осмысленным
    yield index.name, index.dtype


def get_useful_indexes(df: DataFrameLike):
    meta_df = get_meta_df(df)
    return [
        name
        for name, dtype in iter_index_levels(meta_df)
        if not is_internal_dvt_name(name)
    ]


def normalize_index_for_db_write(pdf: pd.DataFrame) -> pd.DataFrame:
    """Normalize named pandas index levels before a DB insert.

    Internal DVT index levels are implementation details and must never become DB columns.
    If a named index already has an ordinary column with the same name, the ordinary column
    is the business-field source of truth (Read V3 dual-role index/column contract). Genuine
    named index-only fields keep the legacy behavior and are materialized as columns.
    """
    working = pdf
    for level_idx in range(working.index.nlevels - 1, -1, -1):
        index_name = working.index.names[level_idx]
        if index_name is None:
            continue

        should_drop = is_internal_dvt_name(index_name) or index_name in working.columns
        working = working.reset_index(level=level_idx, drop=should_drop)

    return working
