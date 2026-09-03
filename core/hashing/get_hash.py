from typing import Any
from dataclasses import is_dataclass

import pandas as pd
import dask.dataframe as dd

from pydantic import BaseModel
from sqlalchemy import Engine

from ._dataclasses import _get_dataclass_model_hash, _get_dataclass_object_hash
from ._dask import _get_dask_hash, _get_series_hash
from ._pandas import _get_pandas_hash
from ._pydantic import _get_pydantic_object_hash, _get_pydantic_model_hash
from ._sqlalchemy import _get_sa_engine_hash
from .hasher import _new_hasher
from .utils import _to_bytes_fast, _update_many, _finalize


def get_hash(obj: Any, deep: bool = False) -> bytes:
    """
    Универсальный быстрый хэш объектов.
    Поддержка:
      - Pydantic модели (v1/v2)
      - dataclasses
      - pandas.DataFrame
      - dask.dataframe.DataFrame
      - sqlalchemy.Engine

    deep=True учитывается для pandas/dask.
    """
    # Pydantic
    if isinstance(obj, BaseModel):
        return _get_pydantic_object_hash(obj)

    if isinstance(obj, type) and issubclass(obj, BaseModel):
        return _get_pydantic_model_hash(obj)

    # dataclasses
    # is_dataclass() возвращает True и для класса, и для инстанса,
    # поэтому разделяем эти случаи.
    if is_dataclass(obj):
        if isinstance(obj, type):
            return _get_dataclass_model_hash(obj)

        return _get_dataclass_object_hash(obj, deep=deep)

    # pandas
    if isinstance(obj, pd.DataFrame):
        return _get_pandas_hash(obj, deep=deep)

    # dask
    if isinstance(obj, dd.DataFrame):
        return _get_dask_hash(obj, deep=deep)

    # SQLAlchemy Engine
    if isinstance(obj, Engine):
        return _get_sa_engine_hash(obj)

    # dask/pandas Series column
    if isinstance(obj, dd.Series) or isinstance(obj, pd.Series):
        return _get_series_hash(obj)

    if isinstance(obj, (type(Ellipsis), type(None))):
        obj = str(obj)

    h = _new_hasher()

    if isinstance(obj, str):
        h.update(_to_bytes_fast(obj))
        return _finalize(h)

    if isinstance(obj, (list, tuple)):
        payload = [get_hash(v, deep=deep).hex() for v in obj]
        _update_many(h, [_to_bytes_fast(payload)])
        return _finalize(h)

    if isinstance(obj, set):
        # Важно: set unordered, поэтому сортируем хэши.
        payload = sorted(get_hash(v, deep=deep).hex() for v in obj)
        _update_many(h, [_to_bytes_fast(payload)])
        return _finalize(h)

    if isinstance(obj, dict):
        payload = {
            str(k): get_hash(v, deep=deep).hex()
            for k, v in sorted(obj.items(), key=lambda item: str(item[0]))
        }
        _update_many(h, [_to_bytes_fast(payload)])

    else:
        cls_tag = f"{obj.__class__.__module__}:{obj.__class__.__qualname__}"
        payload = _to_bytes_fast(obj)
        _update_many(h, [_to_bytes_fast(cls_tag), b"|", payload])

    return _finalize(h)