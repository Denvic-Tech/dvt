from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import dask.dataframe as dd
import pandas as pd


@dataclass
class _PartitionWriteCallable:
    handler: Callable

    def __call__(self, pdf: pd.DataFrame) -> pd.Series:
        return pd.Series([int(self.handler(pdf) or 0)], name="rows_written", dtype="int64")

    def __dask_tokenize__(self) -> tuple[str, int]:
        return (type(self).__name__, id(self.handler))


def process_partitions_bounded(
    ddf: dd.DataFrame,
    handler: Callable,
    *,
    max_workers: int,
) -> int:
    # Not ``to_delayed()``: it runs Dask's blockwise fusion pass, which is superlinear on DVT
    # node graphs (a lifecycle tap after every node). ``compute()`` below does not fuse.
    if ddf.npartitions == 0:
        return 0

    partition_writer = _PartitionWriteCallable(handler=handler)

    if max_workers <= 1:
        results = ddf.map_partitions(
            partition_writer,
            meta=pd.Series(name="rows_written", dtype="int64"),
        ).compute(scheduler="sync")
    else:
        results = ddf.map_partitions(
            partition_writer,
            meta=pd.Series(name="rows_written", dtype="int64"),
        ).compute(scheduler="threads", num_workers=max_workers)

    return sum(int(result or 0) for result in results.tolist())
