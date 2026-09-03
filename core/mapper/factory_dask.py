from __future__ import annotations

import sys
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Optional, Tuple, Union

from dask import compute
import dask.dataframe as dd
import pandas as pd
from loguru import logger
from pandas.api.types import (
    is_bool_dtype,
    is_complex_dtype,
    is_datetime64_any_dtype,
    is_float_dtype,
    is_integer_dtype,
    is_object_dtype,
    is_string_dtype,
    is_timedelta64_dtype,
)
from pandas import PeriodDtype
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    Numeric,
    DateTime,
    Engine,
    Float,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Integer,
    text,
    Text
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Mapper, declarative_base
from sqlalchemy.types import TypeDecorator

from core.mapper import type_decorators as td

# --- Optional ClickHouse / MySQL handling (same logic as pandas version) ---
try:
    from sqlalchemy.dialects.postgresql import TIMESTAMP as PGTimestamp
    from clickhouse_sqlalchemy.types import DateTime as CHDatetime, Nullable  # type: ignore
    from clickhouse_sqlalchemy.drivers.base import ClickHouseDialect  # type: ignore
    from clickhouse_sqlalchemy.engines import MergeTree  # type: ignore
    from sqlalchemy.dialects.mysql import VARCHAR  # type: ignore

    CH_TYPES = sys.modules["clickhouse_sqlalchemy.types"]
except ImportError:  # pragma: no cover – optional deps
    ClickHouseDialect = type("ClickHouseDialect", (), {})  # type: ignore
    MergeTree = None  # type: ignore
    CHDatetime = DateTime  # type: ignore
    CH_TYPES = None  # type: ignore
    Nullable = None  # type: ignore
    VARCHAR = None  # type: ignore

# ---------------------------------------------------------------------------
INT32_MIN, INT32_MAX = -(2 ** 31), 2 ** 31 - 1
DECIMAL_MAX_PRECISION = 38
DECIMAL_MAX_SCALE = 10


# ---------------------------------------------------------------------------
# Helper utilities that work on **dask Series**
# ---------------------------------------------------------------------------

def _compute_series_sample(series: dd.Series, n: int = 1) -> pd.Series:
    """Return *n* non‑null elements of ``series`` as a pandas Series."""
    return series.dropna().head(n, compute=True)  # type: ignore[arg-type]


def compute_dask_df_stats(df: dd.DataFrame, dialect: Any) -> dict:
    """
    Собирает статистику по Dask DataFrame, минимизируя compute:
    - has_nulls: всегда (быстро).
    - sample: только для object колонок.
    - max_len: только для string/object/categorical и только если диалект MySQL/MariaDB.
    - min/max: только для integer колонок.
    Все compute группируются по типам для эффективности.
    """
    stats = {}
    dtypes = df.dtypes  # Без compute
    has_nulls_dict = df.isna().any().compute()  # Один compute, быстрый

    need_max_len = dialect.name in ("mysql", "mariadb")
    # Опция: Если хотите пропустить min/max для int (всегда BigInteger), раскомментируйте
    # need_min_max = False
    need_min_max = True  # По умолчанию True для точности

    # Колонки, нуждающиеся в sample (только object)
    object_cols = [col for col, dtype in dtypes.items() if is_object_dtype(dtype)]
    samples = {}
    if object_cols:
        sample_tasks = {col: df[col].dropna().head(1) for col in object_cols}
        samples = compute(sample_tasks)[0]  # Один compute для всех samples

    # Колонки, нуждающиеся в max_len (string-like, если need_max_len)
    string_like_cols = [col for col, dtype in dtypes.items() if is_object_dtype(dtype) or is_string_dtype(dtype) or isinstance(dtype, pd.CategoricalDtype)]
    max_lens = {}
    if need_max_len and string_like_cols:
        max_len_tasks = {col: df[col].dropna().astype(str).map(len, meta=('x', 'int64')).max() for col in string_like_cols}
        max_lens = compute(max_len_tasks)[0]  # Один compute для всех max_len

    # Колонки, нуждающиеся в min/max (int, если need_min_max)
    int_cols = [col for col, dtype in dtypes.items() if is_integer_dtype(dtype)]
    mins = {}
    maxs = {}
    if need_min_max and int_cols:
        min_tasks = {col: df[col].min() for col in int_cols}
        max_tasks = {col: df[col].max() for col in int_cols}
        computed_mins, computed_maxs = compute(min_tasks, max_tasks)
        mins = computed_mins
        maxs = computed_maxs

    # Собираем stats для каждой колонки
    for col in df.columns:
        col_stats = {
            'dtype': dtypes[col],
            'has_nulls': has_nulls_dict[col],
        }
        if col in samples:
            col_stats['sample'] = samples[col]
        if col in max_lens:
            col_stats['max_len'] = max_lens[col]
        if col in mins:
            col_stats['min'] = mins[col]
            col_stats['max'] = maxs[col]
        stats[col] = col_stats

    return stats


# ---------------------------------------------------------------------------
# Type inference – mirrors the original logic but uses *distributed* stats
# ---------------------------------------------------------------------------

def get_sqla_type(col_name: str, stats: dict, dialect: Any) -> Any:  # noqa: C901 – complex
    """Infer an SQLAlchemy column type for a *Dask* series."""
    dtype = stats['dtype']
    nullable = stats['has_nulls']

    # ClickHouse / MySQL guards (same as original)
    if dialect.name == "clickhouse" and CH_TYPES is None:
        raise ImportError("Install 'clickhouse_sqlalchemy' to use ClickHouse dialect.")
    if dialect.name in ("mysql", "mariadb") and VARCHAR is None:
        raise ImportError("Install a MySQL driver (pymysql / mysqlclient) to use this dialect.")

    # ------------------------------------------------------------------ 1.
    # object dtype – needs sample inspection
    if is_object_dtype(dtype):
        if 'sample' not in stats or stats['sample'].empty:
            # Если sample не вычислен или empty, assume string
            if dialect.name in ("mysql", "mariadb"):
                max_len = int(stats.get('max_len', 255)) or 1
                return VARCHAR(min(max_len, 255))  # type: ignore[arg-type]

            if dialect.name == "clickhouse":
                string_type_instance = td.StringyType()
                return CH_TYPES.Nullable(string_type_instance) if nullable else string_type_instance

            return td.StringyType()

        sample_series = stats['sample']
        sample_val = sample_series.iloc[0]

        if isinstance(sample_val, str):
            if dialect.name in ("mysql", "mariadb"):
                max_len = int(stats.get('max_len', 255)) or 1
                return VARCHAR(min(max_len, 255))  # type: ignore[arg-type]

            if dialect.name == "clickhouse":
                string_type_instance = td.StringyType()
                return CH_TYPES.Nullable(string_type_instance) if nullable else string_type_instance

            return td.StringyType()

        # bytes / lists / dicts / etc. reuse original decorators
        if isinstance(sample_val, (bytes, bytearray, memoryview)):
            return td.BytesAsBase64()
        if isinstance(sample_val, (dict, list)):
            return td.JsonEncodedType()
        if isinstance(sample_val, pd.Period):
            return td.PeriodAsDate()
        if isinstance(sample_val, datetime):
            return td.DateTimeWithNA()
        if isinstance(sample_val, date):
            return Date
        if isinstance(sample_val, Decimal):
            return Numeric(DECIMAL_MAX_PRECISION, DECIMAL_MAX_SCALE)

        # fallback – stringify
        return td.StringyType()

    # ------------------------------------------------------------------ 2. Period dtype
    if isinstance(dtype, PeriodDtype):
        return td.PeriodAsDate()

    # ------------------------------------------------------------------ 3. Interval dtype
    if isinstance(dtype, pd.IntervalDtype):
        return td.StringyType()

    # ------------------------------------------------------------------ 4. complex numbers
    if is_complex_dtype(dtype):
        if dialect.name in ("mysql", "mariadb"):
            return Text()

        return td.StringyType()

    # ------------------------------------------------------------------ 5. categoricals
    if isinstance(dtype, pd.CategoricalDtype):
        if dialect.name in ("mysql", "mariadb"):
            max_len = int(stats.get('max_len', 255)) or 1
            return VARCHAR(min(max_len, 255))  # type: ignore[arg-type]

        return td.StringyType()

    # ------------------------------------------------------------------ 6. pandas StringDtype / Arrow string
    if is_string_dtype(dtype):
        if dialect.name in ("mysql", "mariadb"):
            max_len = int(stats.get('max_len', 255)) or 1
            return VARCHAR(min(max_len, 255))  # type: ignore[arg-type]

        string_type_instance = td.StringyType()
        if dialect.name == "clickhouse" and nullable:
            return CH_TYPES.Nullable(string_type_instance)

        return td.StringyType()

    # ------------------------------------------------------------------ 7. integers
    if is_integer_dtype(dtype):
        if 'min' in stats and 'max' in stats:
            mx, mn = stats['max'], stats['min']
            base = BigInteger if mx > INT32_MAX or mn < INT32_MIN else Integer
        else:
            # Если min/max не вычислены, используем безопасный BigInteger
            base = BigInteger

        if dialect.name == "clickhouse":
            ch_base = CH_TYPES.Int64 if base is BigInteger else CH_TYPES.Int32  # type: ignore[attr-defined]
            impl = CH_TYPES.Nullable(ch_base) if nullable else ch_base  # type: ignore[attr-defined]
            return td.IntegerWithNA(impl)

        return td.IntegerWithNA(base) if nullable else base

    # ------------------------------------------------------------------ 8. floats
    if is_float_dtype(dtype):
        if dialect.name == "clickhouse":
            base = CH_TYPES.Float64  # type: ignore[attr-defined]
            return base if not nullable else CH_TYPES.Nullable(base)  # type: ignore[attr-defined]
        return td.FloatWithNA() if nullable else Float

    # ------------------------------------------------------------------ 9. booleans
    if is_bool_dtype(dtype):
        if dialect.name == "clickhouse":
            base = CH_TYPES.UInt8  # type: ignore[attr-defined]
            return base if not nullable else CH_TYPES.Nullable(base)  # type: ignore[attr-defined]
        return td.BooleanWithNA() if nullable else Boolean

    # ------------------------------------------------------------------ 10. datetime64
    if is_datetime64_any_dtype(dtype):
        if dialect.name == "postgresql":
            if isinstance(dtype, pd.DatetimeTZDtype):
                return PGTimestamp(timezone=True)  # type: ignore[arg-type]
            return td.DateTimeWithNA() if nullable else DateTime
        if dialect.name == "clickhouse":
            return td.CHNullableDateTimeWithNA() if nullable else td.CHDateTimeWithNA()
        return td.DateTimeWithNA()

    # ------------------------------------------------------------------ 11. timedelta64
    if is_timedelta64_dtype(dtype):
        if dialect.name == "postgresql":
            class IntervalWithNA(TypeDecorator):
                impl = postgresql.INTERVAL  # type: ignore[attr-defined]
                cache_ok = True

                def process_bind_param(self, value, dialect):  # noqa: D401
                    if value is None or pd.isna(value):
                        return None
                    if isinstance(value, pd.Timedelta):
                        return value.to_pytimedelta()
                    return value

            return IntervalWithNA()
        if dialect.name == "clickhouse":
            base = CH_TYPES.Float64  # type: ignore[attr-defined]
            underlying = CH_TYPES.Nullable(base) if nullable else base  # type: ignore[attr-defined]

            class CHIntervalAsFloat(TypeDecorator):
                impl = underlying  # type: ignore[attr-defined]
                cache_ok = True

                def process_bind_param(self, value, dialect):
                    if value is None or pd.isna(value):
                        return None
                    return float(value.total_seconds())

            return CHIntervalAsFloat()
        return td.TimedeltaAsFloat()

    # ------------------------------------------------------------------ fallback
    base = postgresql.TEXT if dialect.name == "postgresql" else td.StringyType()
    if dialect.name == "clickhouse" and nullable:
        return CH_TYPES.Nullable(base)  # type: ignore[attr-defined]

    return base


# ---------------------------------------------------------------------------
# Mapper factory for **Dask DataFrame**
# ---------------------------------------------------------------------------

def build_mapper_from_dask_df(
    df: dd.DataFrame,
    table_name: str,
    engine: Engine,
    *,
    schema: Optional[str] = None,
    primary_key_cols: Optional[Union[str, List[str]]] = "id",
    partition_by: Optional[Union[str, List[str], Any]] = None,
    order_by: Optional[Union[str, List[str], Any]] = None,
) -> Tuple[Any, Any]:
    """Create SQLAlchemy declarative mapper from a **Dask** dataframe."""
    # 1. Создаем временный DataFrame, где индекс становится колонкой.
    #    Все последующие операции по созданию метаданных будут использовать ЕГО.
    df_for_meta = df.reset_index()

    # 2. Собираем статистику с df_for_meta, который содержит ВСЕ колонки.
    all_stats = compute_dask_df_stats(df_for_meta, engine.dialect)  # Передаем dialect для условных вычислений

    dialect = engine.dialect
    metadata = MetaData(schema=schema)
    Base = declarative_base(metadata=metadata)

    pk_list: List[str] = []
    if primary_key_cols:
        pk_list = [primary_key_cols] if isinstance(primary_key_cols, str) else list(primary_key_cols)

    table_kw_args = {"extend_existing": True}
    if schema:
        table_kw_args["schema"] = schema

    table_pos_args: List[Any] = []

    if dialect.name == "clickhouse":
        if MergeTree is None:
            raise ImportError("Install 'clickhouse_sqlalchemy' for ClickHouse support.")

        def _clause(expr: Any):
            return text(expr) if isinstance(expr, str) else expr

        if not order_by:
            # 3. Используем колонки из df_for_meta, чтобы 'Код товара' был доступен.
            order_by = pk_list if pk_list else tuple(df_for_meta.columns[:1])
            logger.info("No 'order_by' specified – using %s", order_by)

        mt_engine = MergeTree(
            partition_by=_clause(partition_by) if partition_by else tuple(),
            order_by=_clause(order_by),
            primary_key=_clause(pk_list) if pk_list else tuple(),
        )
        table_pos_args.append(mt_engine)

    if len(pk_list) > 1:
        table_pos_args.append(PrimaryKeyConstraint(*pk_list, name=f"{table_name}_pk"))

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

    attrs: dict[str, Any] = {
        "__tablename__": table_name,
        "__table_args__": (*table_pos_args, table_kw_args),
        "to_dict": to_dict,
    }

    # 4. Проверяем наличие PK колонок в df_for_meta.
    pk_cols_in_df = [c for c in pk_list if c in df_for_meta.columns]

    # 5. Итерируемся по колонкам df_for_meta, чтобы создать SQLAlchemy Column для каждой.
    for col_name in df_for_meta.columns:
        # Пропускаем стандартный числовой индекс, если он появился и не был частью исходных данных.
        if col_name == 'index' and 'index' not in df.columns and df.index.name is None:
            logger.debug("Skipping synthetic 'index' column from metadata.")
            continue

        col_stats = all_stats[col_name]
        sqla_type_instance = get_sqla_type(col_name, col_stats, dialect)
        nullable = col_stats['has_nulls']
        is_primary = col_name in pk_list and len(pk_list) == 1

        if nullable and col_name in pk_list:
            raise ValueError(
                f"Column '{col_name}' is nullable but part of the primary key.")

        col_kwargs = {"primary_key": is_primary, "nullable": nullable}
        if is_primary:
            col_kwargs["autoincrement"] = False

        attrs[col_name] = Column(col_name, sqla_type_instance, **col_kwargs)

    if not pk_cols_in_df:
        logger.warning("PK columns %s not found – adding synthetic 'id'", pk_list)
        if "id" not in attrs:
            attrs["id"] = Column("id", Integer, primary_key=True, autoincrement=True)

    raw = table_name.capitalize()
    class_name = "".join(c if c.isalnum() else "_" for c in raw) or "MappedTable"
    if not class_name[0].isalpha():
        class_name = f"MappedTable_{class_name}"

    try:
        MappedClass = type(class_name, (Base,), attrs)
    except ArgumentError as exc:
        logger.error("Failed building mapper '%s': %s", class_name, exc)
        raise

    return Base, MappedClass