import asyncio
from typing import Any, ClassVar, Literal

import dask.dataframe as dd

from services.task_benchmarking.metrics import record_metric

from src.node_dsl import InputField, SignalOutputBaseNode


class BenchmarkMaterialize(SignalOutputBaseNode):
    """Benchmark sink: computes the input DataFrame and records the materialized row count."""

    TITLE = "Benchmark Materialize"
    CATEGORY = "Benchmark"
    TAGS: ClassVar[list[str]] = ["Testing"]
    VISIBLE = False
    CACHABLE = False
    OUTPUT_NODE = True

    df: dd.DataFrame = InputField(description="DataFrame to compute.")
    num_workers: int = InputField(default=8, min_value=1, description="Dask threads; 1 is sync.")
    mode: Literal["count_rows", "full_pandas"] = InputField(
        default="count_rows",
        description=(
            "count_rows computes partitions and keeps only their lengths; full_pandas collects "
            "the whole frame into one pandas DataFrame (preview-like peak memory)."
        ),
    )

    def _compute_kwargs(self) -> dict[str, Any]:
        # The DVT dask fork allows public operation callbacks only with local schedulers.
        if self.num_workers <= 1:
            return {"scheduler": "sync"}
        return {"scheduler": "threads", "num_workers": self.num_workers}

    def _materialize(self) -> dict[str, int]:
        compute_kwargs = self._compute_kwargs()
        if self.mode == "full_pandas":
            pdf = self.df.compute(**compute_kwargs)
            return {
                "rows": len(pdf),
                "pandas_bytes": int(pdf.memory_usage(deep=True).sum()),
            }
        lengths = self.df.map_partitions(len, meta=(None, "int64")).compute(**compute_kwargs)
        return {"rows": int(lengths.sum())}

    async def process(self) -> None:
        result = await asyncio.to_thread(self._materialize)
        for key, value in result.items():
            record_metric(self.node_id, key, value)
        record_metric(self.node_id, "mode", self.mode)
        record_metric(self.node_id, "num_workers", self.num_workers)
