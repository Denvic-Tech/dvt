from __future__ import annotations

import pickle
from typing import Any, Optional

import dask.dataframe as dd
import pandas as pd

from .protocol import CacheEngine


class DaskMetaCacheEngine(CacheEngine[dd.DataFrame]):
    """
    Cache engine that serialises only the meta information of a Dask DataFrame.

    The engine avoids triggering any computations on the original dataframe:
    only the lightweight ``_meta`` (empty pandas.DataFrame with the same schema)
    is stored alongside a minimal set of characteristics required to recreate
    a structural placeholder on load.
    """

    name = "dask-meta-v1"

    def can_handle(self, obj: Any) -> bool:
        return isinstance(obj, dd.DataFrame)

    def dump(self, obj: dd.DataFrame) -> tuple[bytes, Optional[dict]]:
        meta_frame: pd.DataFrame = obj._meta
        payload = pickle.dumps(meta_frame, protocol=pickle.HIGHEST_PROTOCOL)
        meta: dict[str, Any] = {
            "npartitions": int(obj.npartitions),
            "meta_only": True,
        }
        return payload, meta

    def load(self, data: bytes, *, meta: Optional[dict] = None) -> dd.DataFrame:
        meta_frame: pd.DataFrame = pickle.loads(data)

        npartitions = 1
        if meta:
            try:
                npartitions = int(meta.get("npartitions", 1))
            except (TypeError, ValueError):
                npartitions = 1
            npartitions = max(1, npartitions)

        # Recreate a Dask DataFrame that carries the same schema but no data.
        return dd.from_pandas(meta_frame.iloc[:0], npartitions=npartitions)
