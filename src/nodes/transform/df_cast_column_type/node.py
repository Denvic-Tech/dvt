from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd
from dask import dataframe as dd

from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.logger import logger


@dataclass(frozen=True)
class _IntegerTruncateCastCallable:
    target_dtype: str

    def __call__(self, series: pd.Series) -> pd.Series:
        numeric = pd.to_numeric(series, errors="raise")
        truncated = numeric.where(numeric.isna(), np.trunc(numeric))
        return pd.Series(truncated, index=series.index, name=series.name).astype(self.target_dtype)

    def __dask_tokenize__(self) -> tuple[str, str]:
        return (type(self).__name__, self.target_dtype)


class DataFrameCastColumnType(DFOutputBaseNode):
    TITLE = "Cast Column Types"
    EMOJI = "🔀"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField()
    # Типы задаются как словарь: {"col_name": "target_type"}
    # target_type может быть 'int', 'float', 'str', 'bool', 'datetime', 'category'
    dtypes: Dict[str, str] = InputField()

    output: dd.DataFrame = OutputField()

    @staticmethod
    def _parse_datetime_target_dtype(dtype_name: str) -> Optional[str]:
        normalized = dtype_name.strip()
        lowered = normalized.lower().replace(" ", "")
        if lowered in {"datetime", "datetime64", "datetime64[ns]"}:
            return None
        if lowered.startswith("datetime64[ns,") and lowered.endswith("]"):
            return normalized[normalized.find(",") + 1:-1].strip()
        return None

    @staticmethod
    def _is_integer_target_dtype(dtype_name: str) -> bool:
        normalized = dtype_name.strip().lower().replace(" ", "")
        return normalized in {
            "int",
            "int8",
            "int16",
            "int32",
            "int64",
            "uint8",
            "uint16",
            "uint32",
            "uint64",
            "int8[pyarrow]",
            "int16[pyarrow]",
            "int32[pyarrow]",
            "int64[pyarrow]",
            "uint8[pyarrow]",
            "uint16[pyarrow]",
            "uint32[pyarrow]",
            "uint64[pyarrow]",
            "int8[python]",
            "int16[python]",
            "int32[python]",
            "int64[python]",
            "uint8[python]",
            "uint16[python]",
            "uint32[python]",
            "uint64[python]",
            "int64dtypedtype",
            "int32dtypedtype",
            "int16dtypedtype",
            "int8dtypedtype",
        } or normalized.startswith("int") or normalized.startswith("uint")

    @staticmethod
    def _cast_integer_series(series: dd.Series, column_name: str, target_dtype: str) -> dd.Series:
        cast_callable = _IntegerTruncateCastCallable(target_dtype=target_dtype)
        return series.map_partitions(
            cast_callable,
            meta=(column_name, target_dtype),
        )

    @staticmethod
    def _cast_datetime_series(series: dd.Series, column_name: str, tz: Optional[str]) -> dd.Series:
        parsed = dd.to_datetime(series, errors="coerce", utc=True)
        if tz is None:
            return parsed.map_partitions(
                lambda s: s.dt.tz_localize(None).astype("datetime64[ns]"),
                meta=(column_name, "datetime64[ns]"),
            )

        tz_name = tz.strip()
        if tz_name.upper() == "UTC":
            return parsed.map_partitions(
                lambda s: s.astype("datetime64[ns, UTC]"),
                meta=(column_name, "datetime64[ns, UTC]"),
            )

        target_dtype = f"datetime64[ns, {tz_name}]"
        return parsed.map_partitions(
            lambda s: s.dt.tz_convert(tz_name).astype(target_dtype),
            meta=(column_name, target_dtype),
        )

    def process(self):
        logger.info(f"Casting DataFrame column types: {self.dtypes}")
        try:
            output = self.df
            plain_dtypes: Dict[str, str] = {}

            for column_name, target_dtype in self.dtypes.items():
                normalized_target_dtype = target_dtype.strip()
                target_tz = self._parse_datetime_target_dtype(target_dtype)
                is_datetime_cast = target_tz is not None or target_dtype.strip().lower().replace(" ", "") in {
                    "datetime",
                    "datetime64",
                    "datetime64[ns]",
                }
                if not is_datetime_cast:
                    if self._is_integer_target_dtype(normalized_target_dtype):
                        output = output.assign(
                            **{
                                column_name: self._cast_integer_series(
                                    output[column_name],
                                    column_name,
                                    normalized_target_dtype,
                                )
                            }
                        )
                        continue
                    plain_dtypes[column_name] = normalized_target_dtype
                    continue

                output = output.assign(
                    **{
                        column_name: self._cast_datetime_series(
                            output[column_name], column_name, target_tz
                        )
                    }
                )

            if plain_dtypes:
                output = output.astype(plain_dtypes)

            self.output = output
            logger.info(f"Casted DataFrame dtypes: {self.output.dtypes}")
        except Exception as e:
            logger.error(f"Error casting column types: {e}")
            raise
