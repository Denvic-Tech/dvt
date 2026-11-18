from pathlib import Path
from typing import ClassVar, Literal

import dask.dataframe as dd

from services.task_benchmarking import store
from services.task_benchmarking.metrics import record_metric

from src.node_dsl import DFOutputBaseNode, InputField, OutputField


class BenchmarkStoreRead(DFOutputBaseNode):
    """Lazy DataFrame over the partition files written by BenchmarkStoreWrite.

    One dask partition per file, in file order; a partition is read only when it is computed.
    The first file is read in ``process()`` to build the meta.
    """

    TITLE = "Benchmark Store Read"
    CATEGORY = "Benchmark"
    TAGS: ClassVar[list[str]] = ["Testing"]
    VISIBLE = False
    CACHABLE = False

    path: str = InputField(description="Store directory written by BenchmarkStoreWrite.")
    format: Literal["parquet", "arrow_ipc", "dvt_codec"] = InputField(
        default="parquet", description="File format of the partitions."
    )

    output: dd.DataFrame = OutputField()

    def process(self) -> None:
        files = store.partition_files(Path(self.path), self.format)
        if not files:
            raise FileNotFoundError(f"No {self.format} partitions in {self.path}")
        meta = store.read_partition(files[0], self.format).iloc[:0]
        self.output = dd.from_map(
            store.read_partition,
            [str(path) for path in files],
            fmt=self.format,
            meta=meta,
            label="benchmark-store-read",
        )
        record_metric(self.node_id, "partitions", len(files))
        record_metric(self.node_id, "store_bytes", sum(path.stat().st_size for path in files))
