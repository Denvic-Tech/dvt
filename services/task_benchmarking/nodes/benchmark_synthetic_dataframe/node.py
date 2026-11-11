from typing import ClassVar, Literal

import dask.dataframe as dd
import pandas as pd

from services.task_benchmarking import synthetic
from services.task_benchmarking.metrics import record_metric

from src.node_dsl import DFOutputBaseNode, InputField, OutputField


def _generate_partition(spec: synthetic.PartitionSpec, *, schema: str, seed: int) -> pd.DataFrame:
    return synthetic.generate_partition(schema, spec, seed)


class BenchmarkSyntheticDataFrame(DFOutputBaseNode):
    """Lazy deterministic synthetic DataFrame: partitions are generated only when computed."""

    TITLE = "Benchmark Synthetic DataFrame"
    CATEGORY = "Benchmark"
    TAGS: ClassVar[list[str]] = ["Testing"]
    VISIBLE = False
    CACHABLE = False

    rows: int = InputField(min_value=0, description="Total number of rows.")
    npartitions: int = InputField(default=16, min_value=1, description="Number of partitions.")
    seed: int = InputField(default=42, description="Random seed; equal seeds give equal data.")
    schema: Literal["wide_mixed", "numeric"] = InputField(
        default="wide_mixed",
        description="Synthetic column set.",
    )

    output: dd.DataFrame = OutputField()

    def process(self) -> None:
        # Each partition is a separate from_map task, so N rows are never held in memory at
        # once. Every partition has its own RangeIndex starting at 0, so divisions stay unknown.
        self.output = dd.from_map(
            _generate_partition,
            synthetic.partition_plan(self.rows, self.npartitions),
            schema=self.schema,
            seed=self.seed,
            meta=synthetic.partition_meta(self.schema),
            label="benchmark-synthetic",
        )
        record_metric(self.node_id, "rows", self.rows)
