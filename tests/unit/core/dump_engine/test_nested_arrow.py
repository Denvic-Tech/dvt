import pandas as pd
import pyarrow as pa
import pytest

from core.dump_engine._pandas import UniversalPyArrowCacheEngine


@pytest.mark.parametrize("empty", [False, True])
def test_nested_arrow_and_scalar_dtypes_survive_cache(empty):
    dtype = pd.ArrowDtype(pa.list_(pa.struct([("key", pa.string()), ("value", pa.binary())])))
    frame = pd.DataFrame(
        {
            "headers": pd.Series(
                [[{"key": "dup", "value": b"\xff"}, {"key": "dup", "value": None}], [], None],
                dtype=dtype,
            ),
            "binary": pd.Series([b"\xff", b"", None], dtype="binary[pyarrow]"),
            "ordinary": pd.Series([1, 2, 3], dtype="int32"),
            "nullable": pd.Series([1, None, 3], dtype="Int64"),
            "period": pd.period_range("2024-01", periods=3, freq="M"),
        }
    )
    if empty:
        frame = frame.iloc[:0]
    engine = UniversalPyArrowCacheEngine()
    data, meta = engine.dump(frame)
    pd.testing.assert_frame_equal(engine.load(data, meta=meta), frame)
