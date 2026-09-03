from collections.abc import Hashable
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Literal

import numpy as np
import pandas as pd
from pandas.api.types import (
    is_extension_array_dtype,
    is_datetime64_any_dtype,
    is_timedelta64_dtype,
    is_float_dtype,
)
from core.types import DataFrameLike
from core.types import DataFrameMetadata
from core.types import Column
from core.types.column import DTypeMetadata
from core.types import DataType
from core.utils import get_meta_df, iter_index_levels, is_internal_dvt_name


def _detect_dtype_origin(dtype: Any) -> Literal["numpy", "pandas", "python"]:
    if isinstance(dtype, np.dtype):
        return "numpy"

    dtype_module = getattr(dtype.__class__, "__module__", "")
    if dtype_module.startswith("pandas"):
        return "pandas"
    if dtype_module.startswith("numpy"):
        return "numpy"

    scalar_type = getattr(dtype, "type", None)
    scalar_module = getattr(scalar_type, "__module__", "")
    if scalar_module.startswith("pandas"):
        return "pandas"
    if scalar_module.startswith("numpy"):
        return "numpy"

    return "python"


def _stringify_attr(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _intify_attr(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _get_scalar_type_name(dtype: Any) -> str | None:
    scalar_type = getattr(dtype, "type", None)
    if scalar_type is None:
        return None
    return getattr(scalar_type, "__name__", str(scalar_type))


def _build_dtype_metadata(dtype: Any) -> DTypeMetadata:
    categories = getattr(dtype, "categories", None)
    categories_count = None
    categories_dtype = None
    if categories is not None:
        categories_count = len(categories)
        categories_dtype = _stringify_attr(getattr(categories, "dtype", None))

    return DTypeMetadata(
        name=getattr(dtype, "name", None) or str(dtype),
        class_name=dtype.__class__.__name__,
        origin=_detect_dtype_origin(dtype),
        repr=str(dtype),
        module=getattr(dtype.__class__, "__module__", None),
        kind=_stringify_attr(getattr(dtype, "kind", None)),
        itemsize=_intify_attr(getattr(dtype, "itemsize", None)),
        is_extension=bool(pd.api.types.is_extension_array_dtype(dtype)),
        scalar_type=_get_scalar_type_name(dtype),
        storage=_stringify_attr(getattr(dtype, "storage", None)),
        unit=_stringify_attr(getattr(dtype, "unit", None)),
        timezone=_stringify_attr(getattr(dtype, "tz", None)),
        ordered=getattr(dtype, "ordered", None),
        categories_count=categories_count,
        categories_dtype=categories_dtype,
    )


@lru_cache(maxsize=256)
def _build_dtype_metadata_cached(dtype: Hashable) -> DTypeMetadata:
    return _build_dtype_metadata(dtype)


def _get_dtype_metadata(dtype: Any) -> DTypeMetadata:
    if isinstance(dtype, Hashable):
        return _build_dtype_metadata_cached(dtype)
    return _build_dtype_metadata(dtype)

def is_nullable_dtype(dtype) -> bool:

    dtype = pd.api.types.pandas_dtype(dtype)

    # pandas extension dtypes (Int64, boolean, string, Float64 и т.д.)
    if is_extension_array_dtype(dtype):
        return True

    # datetime / timedelta → поддерживают NaT
    if is_datetime64_any_dtype(dtype) or is_timedelta64_dtype(dtype):
        return True

    # float → поддерживает NaN
    if is_float_dtype(dtype):
        return True

    return False

def get_df_metadata(df: DataFrameLike) -> DataFrameMetadata:
    """
    Возвращает схему (метаданные) DataFrame.

    Метод предоставляет информацию о названиях и типах колонок,
    которую можно использовать для подсказок, валидации и визуализации.
    """

    # TODO: Идея! Опционально передавать связанную ноду (предыдущую), если передана - брать метаданные оттуда.

    meta_df = get_meta_df(df)

    columns_types_map: Dict[str, Any] = meta_df.dtypes.to_dict()
    columns: List[Column] = []
    columns_name_to_idx: Dict[str, int] = {}
    for column_name, dtype in columns_types_map.items():
        if is_internal_dvt_name(column_name):
            continue

        data_type = DataType.from_type(dtype)
        dtype_metadata = _get_dtype_metadata(dtype)
        columns_name_to_idx[column_name] = len(columns)
        columns.append(Column(
            name=column_name,
            dtype=data_type,
            dtype_metadata=dtype_metadata,
            index=False,
            nullable=is_nullable_dtype(dtype)
        ))

    for idx_name, idx_dtype in iter_index_levels(meta_df):
        if is_internal_dvt_name(idx_name):
            continue

        idx_data_type = DataType.from_type(idx_dtype)
        idx_dtype_metadata = _get_dtype_metadata(idx_dtype)
        existing_idx = columns_name_to_idx.get(idx_name)
        if existing_idx is None:
            columns_name_to_idx[idx_name] = len(columns)
            columns.append(Column(
                name=idx_name,
                dtype=idx_data_type,
                dtype_metadata=idx_dtype_metadata,
                index=True
            ))
            continue

        current = columns[existing_idx]
        current_dtype_is_known = current.dtype != DataType.UNKNOWN
        columns[existing_idx] = Column(
            name=current.name,
            dtype=current.dtype if current_dtype_is_known else idx_data_type,
            dtype_metadata=current.dtype_metadata if current_dtype_is_known else idx_dtype_metadata,
            nullable=current.nullable,
            index=True,
        )

    return DataFrameMetadata(
        columns=columns
    )
