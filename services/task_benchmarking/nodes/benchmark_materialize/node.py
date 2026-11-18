import asyncio
from itertools import pairwise
from typing import Any, ClassVar, Literal

import dask.dataframe as dd
import numpy as np
import pandas as pd

from services.task_benchmarking.metrics import record_metric

from src.node_dsl import InputField, SignalOutputBaseNode

_NS_PER_S = 1_000_000_000
_INT_SUM_CHUNK = 1_000_000


def _exact_int_sum(values: np.ndarray) -> int:
    """Exact sum of int64 values: numpy per chunk when it cannot overflow, Python ints otherwise."""
    total = 0
    for start in range(0, values.size, _INT_SUM_CHUNK):
        chunk = values[start : start + _INT_SUM_CHUNK]
        if int(np.abs(chunk).max()) * chunk.size < 2**63:
            total += int(chunk.sum())
        else:
            total += sum(int(value) for value in chunk.tolist())
    return total


def _column_checksum(series: pd.Series) -> dict[str, Any]:
    """Order-independent summary of one column: non-null count plus a type-specific sum.

    Integers and booleans give an exact ``int`` sum, floats a ``float`` sum, datetimes the
    ``int`` sum of whole seconds since the epoch (UTC for tz-aware values), text the ``int`` sum
    of value lengths. Other dtypes get only the count.
    """
    values = series.dropna()
    summary: dict[str, Any] = {"count": len(values)}
    dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype) or pd.api.types.is_integer_dtype(dtype):
        summary["sum"] = _exact_int_sum(values.to_numpy(dtype="int64"))
    elif pd.api.types.is_float_dtype(dtype):
        summary["sum"] = float(values.sum())
    elif pd.api.types.is_datetime64_any_dtype(dtype):
        if getattr(dtype, "tz", None) is not None:
            values = values.dt.tz_convert("UTC").dt.tz_localize(None)
        seconds = values.to_numpy(dtype="datetime64[ns]").astype("int64") // _NS_PER_S
        summary["sum"] = _exact_int_sum(seconds)
    elif pd.api.types.is_string_dtype(dtype) or pd.api.types.is_object_dtype(dtype):
        summary["sum"] = int(values.astype("string").str.len().sum())
    return summary


def _partition_checksum(pdf: pd.DataFrame, sorted_by: str | None) -> pd.Series:
    stats: dict[str, Any] = {
        "rows": len(pdf),
        "columns": {str(name): _column_checksum(pdf[name]) for name in pdf.columns},
    }
    if sorted_by is not None:
        values = pdf[sorted_by].dropna()
        stats["sorted"] = bool(values.is_monotonic_increasing)
        stats["first"] = values.iloc[0] if len(values) else None
        stats["last"] = values.iloc[-1] if len(values) else None
    return pd.Series([stats], dtype=object)


def _merge_checksums(parts: list[dict[str, Any]], sorted_by: str | None) -> dict[str, Any]:
    columns: dict[str, dict[str, Any]] = {}
    for part in parts:
        for name, summary in part["columns"].items():
            merged = columns.setdefault(name, {})
            for key, value in summary.items():
                merged[key] = merged.get(key, 0) + value
    result: dict[str, Any] = {
        "rows": sum(part["rows"] for part in parts),
        "checksum": columns,
    }
    if sorted_by is not None:
        bounds = [(part["first"], part["last"]) for part in parts if part["first"] is not None]
        result["sorted_ok"] = all(part["sorted"] for part in parts) and all(
            previous_last <= next_first
            for (_, previous_last), (next_first, _) in pairwise(bounds)
        )
    return result


def compute_kwargs(num_workers: int) -> dict[str, Any]:
    # The DVT dask fork allows public operation callbacks only with local schedulers.
    if num_workers <= 1:
        return {"scheduler": "sync"}
    return {"scheduler": "threads", "num_workers": num_workers}


def lazy_result(df: dd.DataFrame, mode: str, sorted_by: str | None) -> Any:
    """Dask collection that ``finish_result`` turns into metrics once computed."""
    if mode == "full_pandas":
        return df
    if mode == "checksum":
        return df.map_partitions(_partition_checksum, sorted_by, meta=(None, "object"))
    return df.map_partitions(len, meta=(None, "int64"))


def finish_result(mode: str, sorted_by: str | None, computed: Any) -> dict[str, Any]:
    if mode == "full_pandas":
        return {
            "rows": len(computed),
            "pandas_bytes": int(computed.memory_usage(deep=True).sum()),
        }
    if mode == "checksum":
        return _merge_checksums(computed.tolist(), sorted_by)
    return {"rows": int(computed.sum())}


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
    mode: Literal["count_rows", "full_pandas", "checksum"] = InputField(
        default="count_rows",
        description=(
            "count_rows computes partitions and keeps only their lengths; full_pandas collects "
            "the whole frame into one pandas DataFrame (preview-like peak memory); checksum "
            "keeps per-column counts and sums to verify the result (slower than count_rows)."
        ),
    )
    sorted_by: str | None = InputField(
        default=None,
        description="checksum mode: also check the output is ascending by this column.",
    )

    def _materialize(self) -> dict[str, Any]:
        computed = lazy_result(self.df, self.mode, self.sorted_by).compute(
            **compute_kwargs(self.num_workers)
        )
        return finish_result(self.mode, self.sorted_by, computed)

    async def process(self) -> None:
        result = await asyncio.to_thread(self._materialize)
        for key, value in result.items():
            record_metric(self.node_id, key, value)
        record_metric(self.node_id, "mode", self.mode)
        record_metric(self.node_id, "num_workers", self.num_workers)
