import asyncio
from typing import Any, ClassVar, Literal

import dask
import dask.dataframe as dd

from services.task_benchmarking.metrics import record_metric
from services.task_benchmarking.nodes.benchmark_materialize.node import (
    compute_kwargs,
    finish_result,
    lazy_result,
)

from src.node_dsl import InputField, SignalOutputBaseNode


class BenchmarkMaterializeConcurrent(SignalOutputBaseNode):
    """Benchmark sink: computes two DataFrames in one ``dask.compute`` call.

    Both branches share one thread pool, and an upstream they have in common is computed once.
    """

    TITLE = "Benchmark Materialize Concurrent"
    CATEGORY = "Benchmark"
    TAGS: ClassVar[list[str]] = ["Testing"]
    VISIBLE = False
    CACHABLE = False
    OUTPUT_NODE = True

    df: dd.DataFrame = InputField(description="First DataFrame to compute (metrics suffix _a).")
    df_b: dd.DataFrame = InputField(description="Second DataFrame to compute (metrics suffix _b).")
    num_workers: int = InputField(default=8, min_value=1, description="Dask threads; 1 is sync.")
    mode: Literal["count_rows", "checksum"] = InputField(
        default="count_rows",
        description="Same as BenchmarkMaterialize, applied to each input.",
    )
    sorted_by: str | None = InputField(
        default=None, description="checksum mode: check that df is ascending by this column."
    )
    sorted_by_b: str | None = InputField(
        default=None, description="checksum mode: check that df_b is ascending by this column."
    )

    def _materialize(self) -> dict[str, Any]:
        lazy_a = lazy_result(self.df, self.mode, self.sorted_by)
        lazy_b = lazy_result(self.df_b, self.mode, self.sorted_by_b)
        computed_a, computed_b = dask.compute(lazy_a, lazy_b, **compute_kwargs(self.num_workers))
        result_a = finish_result(self.mode, self.sorted_by, computed_a)
        result_b = finish_result(self.mode, self.sorted_by_b, computed_b)
        result: dict[str, Any] = {"rows": result_a["rows"] + result_b["rows"]}
        for suffix, part in (("a", result_a), ("b", result_b)):
            for key, value in part.items():
                result[f"{key}_{suffix}"] = value
        return result

    async def process(self) -> None:
        result = await asyncio.to_thread(self._materialize)
        for key, value in result.items():
            record_metric(self.node_id, key, value)
        record_metric(self.node_id, "mode", self.mode)
        record_metric(self.node_id, "num_workers", self.num_workers)
