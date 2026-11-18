from contextlib import nullcontext
from typing import ClassVar, Literal

import dask
import dask.dataframe as dd
import pandas as pd

from services.task_benchmarking import synthetic
from services.task_benchmarking.metrics import record_metric

from src.node_dsl import DFOutputBaseNode, InputField, OutputField


def _generate_partition(
    spec: synthetic.PartitionSpec, *, schema: str, seed: int, key_cardinality: int
) -> pd.DataFrame:
    return synthetic.generate_partition(schema, spec, seed, key_cardinality)


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
    schema: Literal["wide_mixed", "numeric", "wide_text", "dim"] = InputField(
        default="wide_mixed",
        description="Synthetic column set.",
    )
    key_cardinality: int = InputField(
        default=0,
        min_value=0,
        description="Distinct values of an extra int64 'key' column; 0 adds no column.",
    )

    output: dd.DataFrame = OutputField()

    def process(self) -> None:
        # Each partition is a separate from_map task, so N rows are never held in memory at
        # once. Every partition has its own RangeIndex starting at 0, so divisions stay unknown.
        # Object columns stay object: dask would otherwise convert them to Arrow strings.
        keep_objects = synthetic.has_object_columns(self.schema)
        strings = (
            dask.config.set({"dataframe.convert-string": False}) if keep_objects else nullcontext()
        )
        with strings:
            self.output = dd.from_map(
                _generate_partition,
                synthetic.partition_plan(self.rows, self.npartitions),
                schema=self.schema,
                seed=self.seed,
                key_cardinality=self.key_cardinality,
                meta=synthetic.partition_meta(self.schema, self.key_cardinality),
                label="benchmark-synthetic",
            )
        record_metric(self.node_id, "rows", self.rows)
