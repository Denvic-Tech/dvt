from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.db.write_v4 import batching
from core.db.write_v4.batching import SAMPLE_VALUES, estimate_row_bytes, rows_for_bytes


def test_rows_for_bytes_divides_the_target_within_the_bounds() -> None:
    assert rows_for_bytes(1_000, 10, max_rows=1_000) == 100
    assert rows_for_bytes(1_000, 10, max_rows=40) == 40
    assert rows_for_bytes(1_000, 0, max_rows=10_000) == 1_000
    assert rows_for_bytes(1_000, 10**6, max_rows=1_000) == 1
    assert rows_for_bytes(1_000, 10**6, max_rows=1_000, min_rows=5) == 5


def test_fixed_width_and_arrow_columns_count_their_buffers_per_row() -> None:
    rows = 1_000
    frame = pd.DataFrame(
        {
            "id": np.arange(rows, dtype="int64"),
            "amount": np.ones(rows, dtype="float64"),
            "seen_at": pd.date_range("2024-01-01", periods=rows, freq="s"),
            "flag": pd.array([True] * rows, dtype="boolean"),
        }
    )
    text = pd.Series(["x" * 1_000] * rows, dtype="string[pyarrow]")

    assert estimate_row_bytes(frame) == 8 + 8 + 8 + 2
    # The text plus its offset: the Arrow buffers, not the 8-byte reference pandas reports.
    assert 1_000 < estimate_row_bytes(text.to_frame()) <= 1_008


@pytest.mark.parametrize("dtype", [object, "string[python]", "category"])
def test_python_object_columns_are_sized_by_their_values(dtype) -> None:
    values = ["я" * 500, None, "x" * 1_000, None] * 250
    frame = pd.DataFrame({"text": pd.Series(values, dtype=dtype)})

    # Mean UTF-8 length: (1000 + 0 + 1000 + 0) / 4.
    assert estimate_row_bytes(frame) == 500


def test_object_values_of_other_types_and_missing_values() -> None:
    frame = pd.DataFrame(
        {
            "raw": pd.Series([b"abcd", bytearray(b"ab")], dtype=object),
            "number": pd.Series([12345, float("nan")], dtype=object),
        }
    )

    assert estimate_row_bytes(frame) == 3 + 3  # (4 + 2) / 2 and (5 + 0) / 2, rounded half up


def test_object_columns_read_at_most_the_sample_whatever_the_partition_size(monkeypatch) -> None:
    sized: list[object] = []

    def value_bytes(value: object) -> int:
        sized.append(value)
        return 10

    monkeypatch.setattr(batching, "_value_bytes", value_bytes)
    rows = SAMPLE_VALUES * 50
    frame = pd.DataFrame(
        {"a": pd.Series(["v"] * rows, dtype=object), "b": pd.Series(["w"] * rows, dtype=object)}
    )

    assert estimate_row_bytes(frame) == 20
    assert len(sized) == 2 * SAMPLE_VALUES


def test_empty_frames_estimate_one_byte() -> None:
    assert estimate_row_bytes(pd.DataFrame({"id": pd.Series([], dtype="int64")})) == 1
    assert estimate_row_bytes(pd.DataFrame(index=range(3))) == 1
