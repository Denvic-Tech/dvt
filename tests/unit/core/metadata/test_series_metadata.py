import pandas as pd

from core.metadata.series_metadata import get_series_metadata
from core.types import DataType


def test_get_series_metadata_uses_name_and_dtype():
    series = pd.Series([1, 2, 3], name="amount")

    meta = get_series_metadata(series)

    assert meta.name == "amount"
    assert meta.column_data.name == "amount"
    assert meta.column_data.dtype == DataType.INT
    assert meta.column_data.index is False
