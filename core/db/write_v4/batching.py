"""Automatic batch size of write_v4 executors: a byte target over the estimated row width.

An executor that sizes its batches by bytes keeps its own target and row bounds next to its code
(``executors/ch.py``, ``pg.py``, ``mssql.py``, ``mysql.py``) and uses ``rows_for_bytes`` with the
row width of the partition it writes. An explicit ``WriteRequest.rows_per_batch`` bypasses this.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

# Values measured per column without a cheap size (object, Python strings, categoricals).
SAMPLE_VALUES = 1_024


def rows_for_bytes(target_bytes: int, row_bytes: int, *, max_rows: int, min_rows: int = 1) -> int:
    """Rows of about ``target_bytes`` at ``row_bytes`` per row, in ``min_rows``..``max_rows``."""
    return max(min_rows, min(max_rows, target_bytes // max(1, row_bytes)))


def estimate_row_bytes(frame: pd.DataFrame) -> int:
    """Approximate bytes of the values of one row of ``frame``; at least 1.

    Numeric, datetime, masked and Arrow-backed columns (including Arrow strings) contribute their
    buffer size per row (``nbytes``, which does not read the data). Columns whose storage holds
    Python objects (object dtype, Python-backed strings, categoricals) contribute the mean size of
    up to ``SAMPLE_VALUES`` evenly spaced values: the UTF-8 length of a string, the length of a
    bytes value, ``len(str(value))`` of any other object and 0 for a missing value.
    """
    rows = len(frame)
    if rows == 0 or frame.shape[1] == 0:
        return 1
    positions: np.ndarray | None = None
    total = 0.0
    for index in range(frame.shape[1]):
        series = frame.iloc[:, index]
        if not _holds_python_objects(series.dtype):
            total += series.array.nbytes / rows
            continue
        if positions is None:
            positions = np.unique(
                np.linspace(0, rows - 1, num=min(rows, SAMPLE_VALUES)).astype(np.int64)
            )
        values = series.iloc[positions].tolist()
        total += sum(_value_bytes(value) for value in values) / len(values)
    return max(1, int(total + 0.5))


def _holds_python_objects(dtype: object) -> bool:
    if isinstance(dtype, pd.CategoricalDtype):
        return True
    if isinstance(dtype, pd.StringDtype):
        return dtype.storage == "python"
    return isinstance(dtype, np.dtype) and dtype.kind == "O"


def _value_bytes(value: object) -> int:
    if value is None or value is pd.NA or value is pd.NaT:
        return 0
    if isinstance(value, str):
        return len(value) if value.isascii() else len(value.encode("utf-8", "surrogatepass"))
    if isinstance(value, (bytes, bytearray)):
        return len(value)
    if isinstance(value, memoryview):
        return value.nbytes
    if isinstance(value, float) and math.isnan(value):
        return 0
    return len(str(value))
