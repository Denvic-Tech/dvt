from typing import Any, Tuple

import pandas as pd
import numpy as np

from sqlalchemy import types as sat


try:
    from sqlalchemy.dialects import postgresql as psql
except Exception:
    psql = None

try:
    from sqlalchemy.dialects import mysql as mysql_dialect
except Exception:
    mysql_dialect = None

try:
    from sqlalchemy.dialects import mariadb as mariadb_dialect
except Exception:
    mariadb_dialect = None

try:
    from clickhouse_sqlalchemy import types as ch
except Exception:
    ch = None

try:
    from sqlalchemy.dialects import oracle as oracle_dialect
except ImportError:
    oracle_dialect = None

# --- helpers для pandas dtypes ---

def _pd_int_dtype(bits: int, nullable: bool) -> Any:
    """Pandas (nullable/non-nullable) int dtype."""
    if nullable:
        return {8: pd.Int8Dtype(),
                16: pd.Int16Dtype(),
                32: pd.Int32Dtype(),
                64: pd.Int64Dtype()}[bits]
    else:
        return {8: np.int8,
                16: np.int16,
                32: np.int32,
                64: np.int64}[bits]


def _pd_uint_dtype(bits: int, nullable: bool) -> Any:
    """Pandas (nullable) unsigned int dtype. Ненуллабл → обычный numpy uint."""
    if nullable:
        return {8: pd.UInt8Dtype(),
                16: pd.UInt16Dtype(),
                32: pd.UInt32Dtype(),
                64: pd.UInt64Dtype()}[bits]
    else:
        return {8: np.uint8,
                16: np.uint16,
                32: np.uint32,
                64: np.uint64}[bits]


def _pd_bool_dtype(nullable: bool) -> Any:
    """
    Pandas Boolean DType
    потому что `pd.BooleanDtype` медленнее, чем np.bool_
    """
    # return pd.BooleanDtype() if nullable else np.bool_
    return pd.BooleanDtype()


def _pd_str_dtype(use_string_dtype: bool) -> Any:
    """string[python] даёт нормальный NA, иначе object."""
    return pd.StringDtype() if use_string_dtype else object


def _pd_dt_tz_dtype(tz: str) -> Any:
    return pd.DatetimeTZDtype(tz=tz)


# --- основное преобразование SQLA type -> pandas dtype ---

def dtype_from_sqla_type(
        col_type: Any,
        *,
        nullable: bool,
        dialect_name: str,
        tz_for_timestamptz: str = "UTC",
        decimal_as_float: bool = True,
        use_string_dtype: bool = True,
        enum_as_category: bool = False,
) -> Tuple[Any, bool, bool]:
    """
    Вернуть (pandas_dtype, is_datetime_tz, is_datetime_naive) по SQLAlchemy type.
    Флаги пригодятся, если захочешь дополнительно прогонять конвертацию данных.
    """
    # --- PostgreSQL специфичные типы ---
    if psql is not None:
        if isinstance(col_type, psql.UUID):
            return _pd_str_dtype(use_string_dtype), False, False
        if isinstance(col_type, (psql.JSON, psql.JSONB)):
            return object, False, False
        if isinstance(col_type, psql.INET):
            return _pd_str_dtype(use_string_dtype), False, False
        if isinstance(col_type, psql.ENUM):
            if enum_as_category:
                return pd.CategoricalDtype(), False, False
            return _pd_str_dtype(use_string_dtype), False, False
        if isinstance(col_type, psql.ARRAY):
            return object, False, False
        if isinstance(col_type, psql.INTERVAL):
            return np.dtype("timedelta64[ns]"), False, False
        if isinstance(col_type, psql.TIMESTAMP):
            if getattr(col_type, "timezone", False):
                return _pd_dt_tz_dtype(tz_for_timestamptz), True, False
            else:
                return np.dtype("datetime64[ns]"), False, True
        if isinstance(col_type, psql.DATE):
            # Будем работать как с datetime64[ns] (полночь).
            return np.dtype("datetime64[ns]"), False, True
        if isinstance(col_type, psql.TIME):
            # pandas не имеет отдельного time64 dtype — оставим объект.
            return object, False, False
        if isinstance(col_type, psql.BYTEA):
            return object, False, False

    if oracle_dialect is not None:
        # Проверка по имени класса (более надежно)
        class_name = col_type.__class__.__name__.upper()

        # Oracle INTERVAL types
        if class_name in ('INTERVAL', 'INTERVALDAYTOSECOND', 'INTERVALYEARTOMONTH'):
            type_str = str(col_type).upper()

            if 'INTERVAL YEAR' in type_str or 'INTERVALYEAR' in type_str:
                # INTERVAL YEAR TO MONTH - сложный тип, оставляем как object
                return object, False, False
            elif 'INTERVAL DAY' in type_str or 'INTERVALDAY' in type_str:
                # INTERVAL DAY TO SECOND - мапим в timedelta
                return np.dtype("timedelta64[ns]"), False, False
            else:
                # По умолчанию считаем, что это INTERVAL DAY TO SECOND
                return np.dtype("timedelta64[ns]"), False, False

        # Альтернативная проверка через isinstance (если диалект импортирован)
        if isinstance(col_type, oracle_dialect.INTERVAL):
            # Проверяем параметры типа
            type_repr = repr(col_type).upper()
            if 'YEAR' in type_repr or hasattr(col_type, 'year_precision'):
                # INTERVAL YEAR TO MONTH
                return object, False, False
            else:
                # INTERVAL DAY TO SECOND
                return np.dtype("timedelta64[ns]"), False, False

        # Oracle TIMESTAMP WITH TIME ZONE
        if isinstance(col_type, oracle_dialect.TIMESTAMP):
            if getattr(col_type, "timezone", False):
                return _pd_dt_tz_dtype(tz_for_timestamptz), True, False
            else:
                return np.dtype("datetime64[ns]"), False, True

        # Oracle DATE (хотя обычно он наследуется от общего sat.Date)
        if isinstance(col_type, oracle_dialect.DATE):
            return np.dtype("datetime64[ns]"), False, True

        # Oracle специфичные строковые типы
        if isinstance(col_type, (oracle_dialect.NCHAR, oracle_dialect.NVARCHAR2)):
            return _pd_str_dtype(use_string_dtype), False, False

        # Oracle RAW тип (бинарные данные)
        if isinstance(col_type, oracle_dialect.RAW):
            return object, False, False

        # Oracle LONG (устаревший, но может встречаться)
        if isinstance(col_type, oracle_dialect.LONG):
            return _pd_str_dtype(use_string_dtype), False, False

        # Oracle CLOB, NCLOB
        if isinstance(col_type, oracle_dialect.CLOB):
            return _pd_str_dtype(use_string_dtype), False, False

        if isinstance(col_type, oracle_dialect.NCLOB):
            return _pd_str_dtype(use_string_dtype), False, False

        # Oracle BLOB
        if isinstance(col_type, oracle_dialect.BLOB):
            return object, False, False

        # Oracle BFILE
        if isinstance(col_type, oracle_dialect.BFILE):
            return object, False, False

        # Oracle ROWID/UROWID
        if isinstance(col_type, oracle_dialect.ROWID):
            return _pd_str_dtype(use_string_dtype), False, False

        # Oracle XMLType
        if class_name == 'XMLTYPE':
            return object, False, False

        # Oracle NUMBER с разными precision/scale (уже обработается в общих типах)
        # Oracle FLOAT/BINARY_FLOAT/BINARY_DOUBLE (уже обработается в общих типах)

    # --- MySQL / MariaDB ---
    if mysql_dialect is not None and isinstance(col_type, (mysql_dialect.DATETIME, mysql_dialect.TIMESTAMP)):
        return np.dtype("datetime64[ns]"), False, True
    if mariadb_dialect is not None and isinstance(col_type, (mariadb_dialect.DATETIME, mariadb_dialect.TIMESTAMP)):
        return np.dtype("datetime64[ns]"), False, True
    if mysql_dialect is not None and isinstance(col_type, (mysql_dialect.JSON,)):
        return object, False, False
    if mariadb_dialect is not None and isinstance(col_type, (mariadb_dialect.JSON,)):
        return object, False, False
    if mysql_dialect is not None and isinstance(col_type, (mysql_dialect.ENUM,)):
        return pd.CategoricalDtype() if enum_as_category else _pd_str_dtype(use_string_dtype), False, False
    if mariadb_dialect is not None and isinstance(col_type, (mariadb_dialect.ENUM,)):
        return pd.CategoricalDtype() if enum_as_category else _pd_str_dtype(use_string_dtype), False, False

    # --- ClickHouse ---
    if ch is not None:
        if isinstance(col_type, ch.Nullable):
            inner = getattr(col_type, "nested_type", None)
            if inner is None:
                return object, False, False

            dtype, is_tz, is_naive = dtype_from_sqla_type(
                inner,
                nullable=True,
                dialect_name=dialect_name,
                tz_for_timestamptz=tz_for_timestamptz,
                decimal_as_float=decimal_as_float,
                use_string_dtype=use_string_dtype,
                enum_as_category=enum_as_category,
            )
            return dtype, is_tz, is_naive

        # Целые
        if isinstance(col_type, ch.UInt8):
            return _pd_uint_dtype(8, nullable), False, False
        if isinstance(col_type, ch.UInt16):
            return _pd_uint_dtype(16, nullable), False, False
        if isinstance(col_type, ch.UInt32):
            return _pd_uint_dtype(32, nullable), False, False
        if isinstance(col_type, ch.UInt64):
            return _pd_uint_dtype(64, nullable), False, False
        if isinstance(col_type, ch.Int8):
            return _pd_int_dtype(8, nullable), False, False
        if isinstance(col_type, ch.Int16):
            return _pd_int_dtype(16, nullable), False, False
        if isinstance(col_type, ch.Int32):
            return _pd_int_dtype(32, nullable), False, False
        if isinstance(col_type, ch.Int64):
            return _pd_int_dtype(64, nullable), False, False

        # Float
        if isinstance(col_type, (ch.Float32,)):
            return np.float32, False, False
        if isinstance(col_type, (ch.Float64,)):
            return np.float64, False, False

        # Date/DateTime
        if isinstance(col_type, (ch.Date, ch.Date32)):
            return np.dtype("datetime64[ns]"), False, True
        if isinstance(col_type, (ch.DateTime, ch.DateTime64)):
            # У ч.типа может быть tz в параметрах — сведём к tz dtype
            return _pd_dt_tz_dtype(tz_for_timestamptz), True, False

        # Строки / Enum / UUID / IP
        if isinstance(col_type, (ch.String, ch.LowCardinality)):
            return _pd_str_dtype(use_string_dtype), False, False
        if isinstance(col_type, (ch.Enum8, ch.Enum16)):
            return pd.CategoricalDtype() if enum_as_category else _pd_str_dtype(use_string_dtype), False, False
        if hasattr(ch, "UUID") and isinstance(col_type, ch.UUID):
            return _pd_str_dtype(use_string_dtype), False, False
        if hasattr(ch, "IPv4") and isinstance(col_type, ch.IPv4):
            return _pd_str_dtype(use_string_dtype), False, False
        if hasattr(ch, "IPv6") and isinstance(col_type, ch.IPv6):
            return _pd_str_dtype(use_string_dtype), False, False

        # Array / Map / Tuple — как объект
        ch_container = tuple(
            t for t in (getattr(ch, "Array", None), getattr(ch, "Map", None), getattr(ch, "Tuple", None)) if t
        )
        if ch_container and isinstance(col_type, ch_container):
            return object, False, False

    # --- Общие SQLAlchemy типы ---
    if isinstance(col_type, sat.Boolean):
        return _pd_bool_dtype(nullable), False, False

    if isinstance(col_type, sat.SmallInteger):
        return _pd_int_dtype(16, nullable), False, False
    if isinstance(col_type, sat.BigInteger):
        return _pd_int_dtype(64, nullable), False, False
    if isinstance(col_type, sat.Integer):
        return _pd_int_dtype(32, nullable), False, False

    if isinstance(col_type, (sat.Float,)):
        return np.float64, False, False

    if isinstance(col_type, (sat.Numeric, sat.DECIMAL)):
        if decimal_as_float:
            return np.float64, False, False
        return object, False, False

    if isinstance(col_type, sat.Date):
        return np.dtype("datetime64[ns]"), False, True

    if isinstance(col_type, sat.DateTime):
        if getattr(col_type, "timezone", False):
            return _pd_dt_tz_dtype(tz_for_timestamptz), True, False
        return np.dtype("datetime64[ns]"), False, True

    if isinstance(col_type, sat.Time):
        return object, False, False
    if isinstance(col_type, (sat.String, sat.Text, sat.Unicode, sat.UnicodeText, sat.LargeBinary, sat.VARBINARY)):
        # LargeBinary / VARBINARY лучше object (bytes)
        if isinstance(col_type, (sat.LargeBinary, sat.VARBINARY)):
            return object, False, False
        return _pd_str_dtype(use_string_dtype), False, False

    # Fallback — объект
    return object, False, False
