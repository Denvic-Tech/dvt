import asyncio
import time
from pathlib import Path
from typing import Any, ClassVar, Literal

import dask.dataframe as dd
import pandas as pd

from services.task_benchmarking import store
from services.task_benchmarking.metrics import record_metric
from services.task_benchmarking.nodes.benchmark_materialize.node import compute_kwargs

from src.node_dsl import InputField, SignalOutputBaseNode


def _write_partition_task(
    pdf: pd.DataFrame,
    root: str,
    fmt: str,
    compression: str | None,
    partition_info: dict[str, Any] | None = None,
) -> pd.Series:
    number = partition_info["number"] if partition_info else 0
    frame_bytes = int(pdf.memory_usage(index=False, deep=True).sum())
    started = time.perf_counter()
    file_bytes = store.write_partition(
        pdf, store.partition_path(Path(root), fmt, number), fmt, compression
    )
    stats = {
        "rows": len(pdf),
        "store_bytes": file_bytes,
        "frame_bytes": frame_bytes,
        "write_s": time.perf_counter() - started,
    }
    return pd.Series([stats], dtype=object)


class BenchmarkStoreWrite(SignalOutputBaseNode):
    """Benchmark barrier: computes ``df`` and writes every partition to one file in ``path``.

    Partition files of any format already in ``path`` are deleted first. Link ``signal_out``
    to the ``signal_in`` of a BenchmarkStoreRead in the same pipeline so it runs afterwards.
    """

    TITLE = "Benchmark Store Write"
    CATEGORY = "Benchmark"
    TAGS: ClassVar[list[str]] = ["Testing"]
    VISIBLE = False
    CACHABLE = False
    OUTPUT_NODE = True

    df: dd.DataFrame = InputField(description="DataFrame to compute and store.")
    path: str = InputField(description="Store directory, created when missing.")
    format: Literal["parquet", "arrow_ipc", "dvt_codec"] = InputField(
        default="parquet", description="File format of the partitions."
    )
    compression: str | None = InputField(
        default=None,
        description="Codec; None is snappy for parquet, uncompressed for arrow_ipc.",
    )
    num_workers: int = InputField(default=8, min_value=1, description="Dask threads; 1 is sync.")

    def _write(self) -> dict[str, Any]:
        root = Path(self.path)
        root.mkdir(parents=True, exist_ok=True)
        store.clear_partitions(root)
        parts = (
            self.df.map_partitions(
                _write_partition_task,
                str(root),
                self.format,
                self.compression,
                meta=(None, "object"),
            )
            .compute(**compute_kwargs(self.num_workers))
            .tolist()
        )
        result: dict[str, Any] = {
            key: sum(part[key] for part in parts)
            for key in ("rows", "store_bytes", "frame_bytes", "write_s")
        }
        result["partitions"] = len(parts)
        return result

    async def process(self) -> None:
        result = await asyncio.to_thread(self._write)
        for key, value in result.items():
            record_metric(self.node_id, key, value)
        record_metric(self.node_id, "format", self.format)
        record_metric(self.node_id, "compression", self.compression)
        record_metric(self.node_id, "num_workers", self.num_workers)
