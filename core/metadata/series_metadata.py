from core.types import Column, DataType
from core.types.common import SeriesLike
from core.types.metadata import SeriesMetadata


def get_series_metadata(series: SeriesLike) -> SeriesMetadata:
    name = str(series.name)
    dtype = DataType.from_type(series.dtype)

    return SeriesMetadata(name=name,
                          column_data=Column(name=name, dtype=dtype, index=False))
