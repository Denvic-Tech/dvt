from typing import Union, TYPE_CHECKING

if TYPE_CHECKING:
    from pandas import DataFrame as PandasDataFrame, Series as PandasSeries
    from dask.dataframe import DataFrame as DaskDataFrame, Series as DaskSeries


DataFrameLike = Union["PandasDataFrame", "DaskDataFrame"]
SeriesLike = Union["PandasSeries", "DaskSeries"]
