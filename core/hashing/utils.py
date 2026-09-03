import datetime
from typing import Any, Iterable

import orjson
import pandas as pd
import numpy as np


def _to_bytes_fast(obj: Any) -> bytes:
    """Быстрая сериализация простых структур в bytes (через orjson при наличии)."""
    if isinstance(obj, pd.Timestamp):
        obj = obj.isoformat()

    if isinstance(obj, np.datetime64):
        obj = str(obj)

    if isinstance(obj, (bytes, bytearray, memoryview)):
        return bytes(obj)

    if isinstance(obj, str):
        return obj.encode("utf-8", errors="surrogatepass")

    try:
        return orjson.dumps(obj)
    except TypeError as e:
        raise TypeError(f"{e} ({type(obj)}) - obj: {obj}")


def _update_many(hasher, parts: Iterable[bytes]) -> None:
    for p in parts:
        hasher.update(p)


def _finalize(hasher) -> bytes:
    # Для blake3/blake2b одинаковый интерфейс digest()
    return hasher.digest()
