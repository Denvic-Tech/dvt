import pandas as pd

from .hasher import _new_hasher
from .utils import _update_many, _to_bytes_fast, _finalize


def _get_pandas_schema_fingerprint(df: pd.DataFrame) -> bytes:
    # Хэшируем колонki, dtypes, shape, тип индекса (без данных)
    hasher = _new_hasher()
    cols = list(map(str, df.columns))
    dtypes = [str(t) for t in df.dtypes.to_list()]
    shape = (df.shape[0], df.shape[1])
    index_type = df.index.__class__.__name__
    _update_many(hasher, [
        _to_bytes_fast(cols), b"|",
        _to_bytes_fast(dtypes), b"|",
        _to_bytes_fast(shape), b"|",
        _to_bytes_fast(index_type)
    ])
    return _finalize(hasher)


def _normalize_pandas_df_to_fingerprint(df: pd.DataFrame) -> pd.DataFrame:
    columns = [c for c in df.columns if pd.api.types.is_hashable(df[c].iloc[0])]
    return df[columns]


def _get_pandas_deep_fingerprint(df: pd.DataFrame) -> bytes:
    """
    Глубокий (по данным) хэш без большого копирования.
    Используем pd.util.hash_pandas_object (uint64 на строку),
    затем обновляем хэш потоком байт (через memoryview).
    """
    df = _normalize_pandas_df_to_fingerprint(df)
    s = pd.util.hash_pandas_object(df, index=True)  # Series[uint64]
    arr = s.values  # numpy ndarray of uint64
    # memoryview без копирования; приводим к байтам
    mv = memoryview(arr).cast('B')
    hasher = _new_hasher()
    # Колонки/типы тоже учитываем (hash_pandas_object не кодирует имена колонок)
    _update_many(hasher, [
        _to_bytes_fast(list(map(str, df.columns))), b"|",
        _to_bytes_fast([str(t) for t in df.dtypes.to_list()]), b"|",
    ])
    hasher.update(mv)
    # Индекс уже учтен (index=True)
    return _finalize(hasher)


def _get_pandas_hash(obj: pd.DataFrame, deep: bool) -> bytes:
    if not isinstance(obj, pd.DataFrame):
        raise TypeError(f"'pd.DataFrame' expected, '{type(obj)}' received")
    return _get_pandas_deep_fingerprint(obj) if deep and not obj.empty else _get_pandas_schema_fingerprint(obj)
