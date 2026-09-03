import pickle
from decimal import Decimal
from io import BytesIO
from typing import Any, Optional

import pandas as pd
import pyarrow as pa
from pyarrow import feather

from core.dump_engine.protocol import CacheEngine
from core.utils import get_useful_indexes


class UniversalPyArrowCacheEngine(CacheEngine[pd.DataFrame]):
    """
    Универсальный кеш для DataFrame (Dask и Pandas)
    Всегда возвращает pandas.DataFrame
    """
    name = "universal-pyarrow-v1"

    def __init__(
            self,
            *,
            max_rows: int | None = None,
            compression: str = 'lz4',
    ) -> None:
        self._max_rows = max_rows
        self._compression = compression

    def can_handle(self, obj: Any) -> bool:
        return isinstance(obj, pd.DataFrame)

    def _dump_meta(self, obj: pd.DataFrame) -> bytes:
        obj = obj.iloc[:0]
        return pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)

    def _load_meta(self, data: bytes) -> pd.DataFrame:
        return pickle.loads(data)

    @staticmethod
    def _is_decimal_mixed_numeric_object(series: pd.Series) -> bool:
        if series.dtype != object:
            return False

        non_null = series[series.notna()]
        if non_null.empty:
            return False

        has_decimal = False
        has_non_decimal_numeric = False
        for value in non_null:
            if isinstance(value, Decimal):
                has_decimal = True
                continue
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                has_non_decimal_numeric = True
                continue
            return False

        return has_decimal and has_non_decimal_numeric

    @classmethod
    def _normalize_decimal_mixed_object_columns(cls, pdf: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
        normalized_pdf = pdf
        changed = False

        for column_name in pdf.columns:
            series = pdf[column_name]
            if not cls._is_decimal_mixed_numeric_object(series):
                continue

            if not changed:
                normalized_pdf = pdf.copy()
                changed = True

            normalized_pdf[column_name] = pd.to_numeric(
                series.map(lambda value: float(value) if isinstance(value, Decimal) else value),
                errors="coerce",
            )

        return normalized_pdf, changed

    def dump(self, obj: pd.DataFrame) -> tuple[bytes, Optional[dict]]:
        if not isinstance(obj, pd.DataFrame):
            raise TypeError(f"{self.__class__.__name__} can handle only pandas.DataFrame")

        pdf = obj if (self._max_rows is None or len(obj) <= self._max_rows) else obj.head(self._max_rows)

        # Сериализуем метаданные для сохранения исходных типов данных
        meta_bytes = self._dump_meta(obj)

        # Arrow/Feather is the fast path. Some object columns (for example mixed
        # Decimal + int/float or arbitrary JSON-like Python values) cannot be
        # represented by a single Arrow dtype without coercion. Execution cache
        # must be lossless, so fall back to pickle instead of normalizing values.
        try:
            arrow_table = pa.Table.from_pandas(
                pdf,
                preserve_index=get_useful_indexes(pdf),
            )
        except (pa.ArrowTypeError, pa.ArrowInvalid, TypeError, ValueError):
            return (
                pickle.dumps(pdf, protocol=pickle.HIGHEST_PROTOCOL),
                {'meta': meta_bytes, 'serialization': 'pickle'},
            )

        buf = BytesIO()
        feather.write_feather(arrow_table, buf, compression=self._compression)

        # Возвращаем данные и метаданные
        return buf.getvalue(), {'meta': meta_bytes, 'serialization': 'feather'}

    def load(
            self,
            data: bytes,
            *,
            meta: Optional[dict] = None
    ) -> pd.DataFrame:
        """Восстанавливает pandas DataFrame из сериализованных данных"""
        if meta and meta.get('serialization') == 'pickle':
            restored = pickle.loads(data)
            if not isinstance(restored, pd.DataFrame):
                raise TypeError("Pickle dataframe cache payload does not contain pandas.DataFrame")
            return restored

        # Missing marker is the legacy universal-pyarrow-v1 format.
        buf = BytesIO(data)
        df = feather.read_feather(buf)

        # Если есть метаданные, восстанавливаем исходные типы данных
        if meta and 'meta' in meta:

            meta_df = self._load_meta(meta['meta'])

            # Восстанавливаем типы колонок
            for col in df.columns:
                if col in meta_df.columns:
                    original_dtype = meta_df[col].dtype
                    current_dtype = df[col].dtype

                    # Применяем исходный dtype, если он отличается
                    if original_dtype != current_dtype:
                        df[col] = df[col].astype(original_dtype)

            # Восстанавливаем тип индекса
            meta_index = meta_df.index

            if isinstance(meta_index, pd.RangeIndex):
                start = meta_index.start
                step = meta_index.step
                stop = start + len(df) * step
                df.index = pd.RangeIndex(start=start, stop=stop, step=step, name=meta_index.name)
            elif isinstance(meta_index, pd.MultiIndex):
                if isinstance(df.index, pd.MultiIndex):
                    df.index = df.index.set_names(meta_index.names)
            elif isinstance(meta_index, pd.DatetimeIndex):
                df.index = pd.DatetimeIndex(df.index, name=meta_index.name, tz=meta_index.tz)
            elif isinstance(meta_index, pd.PeriodIndex):
                df.index = pd.PeriodIndex(df.index, name=meta_index.name, freq=meta_index.freq)
            elif isinstance(meta_index, pd.TimedeltaIndex):
                df.index = pd.TimedeltaIndex(df.index, name=meta_index.name)
            elif isinstance(meta_index, pd.CategoricalIndex):
                df.index = pd.CategoricalIndex(df.index, name=meta_index.name, dtype=meta_index.dtype)
            else:
                if hasattr(meta_index, 'dtype') and hasattr(df.index, 'dtype'):
                    if meta_index.dtype != df.index.dtype:
                        df.index = df.index.astype(meta_index.dtype)

                if meta_index.name is not None:
                    df.index.name = meta_index.name

        return df
