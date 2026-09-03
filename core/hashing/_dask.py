import dask.dataframe as dd
import pandas as pd
from dask.base import tokenize

from .hasher import _new_hasher
from .utils import _update_many, _to_bytes_fast, _finalize


def _summarize_low_level_graph(graph: dict) -> tuple[str, ...]:
    names = set()
    for k in graph.keys():
        if k and isinstance(k, tuple) and isinstance(k[0], str):
            names.add('|'.join([str(part) for part in k]))
        elif isinstance(k, str):
            names.add(k)
    return tuple(sorted(names))


def _get_dask_fingerprint(ddf: dd.DataFrame) -> bytes:
    hasher = _new_hasher()

    meta = ddf._meta  # пустой pandas DF с правильными dtypes
    cols = list(map(str, meta.columns))
    dtypes = [str(t) for t in meta.dtypes.to_list()]
    index_type = meta.index.__class__.__name__

    _update_many(hasher, [
        _to_bytes_fast(cols), b"|",
        _to_bytes_fast(dtypes), b"|",
        _to_bytes_fast(index_type)
    ])

    return _finalize(hasher)


def _hash_pandas_partition(df: pd.DataFrame) -> bytes:
    """
    Вычисляем компактный digest одной партиции pandas без отдачи всего массива наружу.
    """
    # Схема партиции
    h = _new_hasher()
    _update_many(h, [
        _to_bytes_fast(list(map(str, df.columns))), b"|",
        _to_bytes_fast([str(t) for t in df.dtypes.to_list()]), b"|",
    ])

    # Данные партиции
    s = pd.util.hash_pandas_object(df, index=True)
    arr = s.values
    mv = memoryview(arr).cast('B')
    h.update(mv)
    return _finalize(h)


def _get_series_hash(df_series: dd.Series) -> bytes:
    hasher = _new_hasher()

    _update_many(hasher, [
        _to_bytes_fast(df_series.name), b"|",
        _to_bytes_fast(str(df_series.dtype)), b"|",
        _to_bytes_fast(str(df_series.npartitions)), b"|",
        _to_bytes_fast(tokenize(df_series))
    ])
    return _finalize(hasher)


def _get_dask_deep_fingerprint(ddf: dd.DataFrame) -> bytes:
    """
    Глубокий хэш dask DF: считаем digest каждой партиции (в параллели),
    затем детерминированно объединяем. Порядок партиций не влияет: сортируем.
    """
    # возвращаем по 1 digest на партицию (серия object-байтов)
    part_digests = ddf.map_partitions(
        lambda pdf: pd.Series([_hash_pandas_partition(pdf)]),  # по одному элементу
        meta=pd.Series(dtype="object"),
    ).compute()

    # Сортируем для детерминизма независимо от порядка выполнения
    as_bytes: list[bytes] = sorted((bytes(x) for x in part_digests.tolist()))
    h = _new_hasher()
    # Включаем также мета-инфо, чтобы отличать одинаковые данные с иной нарезкой
    _update_many(h, [_get_dask_fingerprint(ddf)])
    for d in as_bytes:
        h.update(d)
        h.update(b"|")
    return _finalize(h)


def _get_dask_hash(obj: dd.DataFrame, deep: bool) -> bytes:
    return _get_dask_deep_fingerprint(obj) if deep else _get_dask_fingerprint(obj)
