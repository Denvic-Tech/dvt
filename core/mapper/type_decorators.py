import json
import base64
from typing import Any, Optional, Union
from datetime import timezone, datetime, date, timedelta

import pandas as pd
from loguru import logger

from sqlalchemy import Date, Integer, Float, DateTime, Text, TypeDecorator, Boolean, LargeBinary, String

from sqlalchemy.engine.interfaces import Dialect

try:
    from clickhouse_sqlalchemy import types as CH_TYPES

except ImportError:
    CH_TYPES = None


class UniversalLiteralString(TypeDecorator):
    """
    Универсальный декоратор, который обеспечивает корректный рендеринг
    строковых литералов для разных диалектов SQL при использовании
    опции `literal_binds=True`.
    """
    impl = String
    cache_ok = True

    def literal_processor(self, dialect):
        """
        Возвращает функцию-обработчик, которая выбирает метод экранирования
        в зависимости от имени диалекта.
        """
        # Определяем диалекты, использующие обратный слэш для экранирования
        # MySQL/MariaDB исключены, т.к. мы используем sql_mode=NO_BACKSLASH_ESCAPES,
        # что заставляет их вести себя по стандарту SQL.
        backslash_escape_dialects = {'clickhouse'}

        def process(value):
            # Эта проверка дублируется в UniversalCompiler, но это делает
            # декоратор самодостаточным и безопасным.
            if pd.isna(value):
                return "NULL"

            # Убеждаемся, что работаем со строкой
            str_value = str(value)

            # Выбираем правильный метод экранирования
            if dialect.name in backslash_escape_dialects:
                # Для ClickHouse: экранируем \ и '
                escaped_value = str_value.replace('\\', '\\\\').replace("'", "\\'")
            else:
                # Для PostgreSQL, SQLite, MSSQL, MySQL (с NO_BACKSLASH_ESCAPES)
                # и как безопасный стандартный вариант: экранируем ' удвоением.
                escaped_value = str_value.replace("'", "''")

            return f"'{escaped_value}'"

        return process


class FloatWithNA(TypeDecorator):
    """Убирает np.nan → None, иначе float(value)."""
    impl = Float
    cache_ok = True

    def process_bind_param(self, value, dialect):
        # любое NaN или pd.NA → NULL
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return float(value)


class _BaseDateTimeWithNA(TypeDecorator):
    """Общие правила: NaT/None → None, Timestamp → datetime (UTC)."""
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or pd.isna(value):
            return None
        if isinstance(value, pd.Timestamp):
            value = value.to_pydatetime()
        if isinstance(value, datetime):
            # ClickHouse хранит время в UTC; делаем aware-UTC
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            else:
                value = value.astimezone(timezone.utc)
            return value
        raise ValueError(f"Invalid datetime value: {value!r}")


class CHDateTimeWithNA(_BaseDateTimeWithNA):
    """ClickHouse → DateTime (NOT NULL)."""

    def load_dialect_impl(self, dialect):
        if dialect.name == "clickhouse" and CH_TYPES:
            return dialect.type_descriptor(CH_TYPES.DateTime)
        return super().load_dialect_impl(dialect)


class CHNullableDateTimeWithNA(_BaseDateTimeWithNA):
    """ClickHouse → Nullable(DateTime)."""

    def load_dialect_impl(self, dialect):
        if dialect.name == "clickhouse" and CH_TYPES:
            return dialect.type_descriptor(CH_TYPES.Nullable(CH_TYPES.DateTime))
        return super().load_dialect_impl(dialect)


class TimedeltaAsFloat(TypeDecorator):
    """Convert pd.Timedelta (и datetime.timedelta) to float (seconds) for storage."""
    impl = Float
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        # для ClickHouse используем Float64 из clickhouse-sqlalchemy
        if dialect.name == "clickhouse" and CH_TYPES is not None:
            return dialect.type_descriptor(CH_TYPES.Float64)
        return dialect.type_descriptor(Float)

    def process_bind_param(self, value: any, dialect: Dialect) -> float | None:
        """Convert value to float (seconds) when sending to the database."""
        logger.debug(f"Processing Timedelta value: {value!r}")

        # Ловим и None, и NaN, и NaT
        if value is None or pd.isna(value):
            return None

        # pd.Timedelta и встроенный datetime.timedelta
        if isinstance(value, (pd.Timedelta, timedelta)):
            return float(value.total_seconds())

        raise ValueError(f"Cannot bind value {value!r} as Timedelta")

    def process_result_value(self, value: float | None, dialect: Dialect) -> pd.Timedelta | None:
        """Convert float (seconds) back to Timedelta when retrieving."""
        return pd.to_timedelta(value, unit='s') if value is not None else None


class BytesAsBase64(TypeDecorator):
    """
    Для ClickHouse → String (Base64-строка).
    Для остальных  → LargeBinary.
    """
    impl = Text  # общий тип, но мы подменим в load_dialect_impl
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        # ClickHouse → String
        if dialect.name == "clickhouse":
            from clickhouse_sqlalchemy import types as ch_types
            return dialect.type_descriptor(ch_types.String)
        # все остальные → LargeBinary
        return dialect.type_descriptor(LargeBinary)

    def process_bind_param(self, value: Any, dialect: Dialect) -> Optional[Union[bytes, str]]:
        logger.debug(f"Processing BytesAsBase64 value: {value!r}")
        if dialect.name == "clickhouse":
            # ClickHouse-driver не любит None.encode()
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return ""
            if isinstance(value, (bytes, bytearray, memoryview)):
                return base64.b64encode(bytes(value)).decode("ascii")
            raise ValueError(f"BytesAsBase64 expected bytes-like, got {type(value).__name__!r}")
        # для остальных СУБД
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return bytes(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Optional[bytes]:
        if dialect.name == "clickhouse":
            return base64.b64decode(value) if value else b""
        return value

    @property
    def python_type(self):
        return bytes


class PeriodAsDate(TypeDecorator):
    impl = Date
    cache_ok = True

    def process_bind_param(self, value, dialect):
        logger.debug(f"Processing PeriodAsDate value: {value!r}")
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        if isinstance(value, pd.Period):
            return value.to_timestamp(how='start').date()
        if isinstance(value, (datetime, date)):
            return value if isinstance(value, date) else value.date()
        raise ValueError(f"Cannot bind value {value!r} as Period")

    def process_result_value(self, value, dialect):
        return value


class DateTimeWithNA(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        logger.debug(f"Processing DateTimeWithNA value: {value!r}")
        if value is None:
            return None
        if isinstance(value, (pd.Timestamp, datetime)) and pd.isna(value):
            return None
        if isinstance(value, pd.Timestamp):
            return value.to_pydatetime()
        if isinstance(value, datetime):
            return value
        raise ValueError(f"Cannot bind value {value!r} as DateTime")

    def process_result_value(self, value, dialect):
        return value


class StringyType(TypeDecorator):
    """
    Умеет сериализовать любые объекты в str.
    Для ClickHouse использует специальный рендерер литералов.
    """
    impl = UniversalLiteralString  # Тип по умолчанию для всех, кроме ClickHouse
    cache_ok = True

    def process_bind_param(self, value: any, dialect: Dialect) -> any:
        if pd.isna(value):
            return "" if dialect.name == "clickhouse" else None
        return str(value)


class JsonEncodedType(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Optional[Union[dict, list]], dialect: Dialect) -> Optional[str]:
        logger.debug(f"Processing JsonEncodedType value: {value!r}")
        return json.dumps(value) if value is not None else None

    def process_result_value(self, value: Optional[str], dialect: Dialect) -> Optional[Union[dict, list]]:
        return json.loads(value) if value is not None else None


# class TimedeltaAsFloat(TypeDecorator):
#     impl = Float
#     cache_ok = True
#
#     def process_bind_param(self, value: Optional[pd.Timedelta], dialect: Dialect) -> Optional[float]:
#         logger.debug(f"Processing TimedeltaAsFloat value: {value!r}")
#         return value.total_seconds() if pd.notna(value) else None
#
#     def process_result_value(self, value: Optional[float], dialect: Dialect) -> Optional[pd.Timedelta]:
#         return pd.to_timedelta(value, unit='s') if value is not None else None


class IntegerWithNA(TypeDecorator):
    """
    Int с поддержкой NaN/NA и numpy-чисел.
    """
    impl = Integer  # базовый SQLAlchemy-тип
    cache_ok = True
    _type_affinity = Integer  # ← КЛАСС, а не строка

    def __init__(self, impl_type=Integer, *args, **kw):
        super().__init__(*args, **kw)
        self.impl = impl_type  # Int32 / Int64 / Integer …

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(self.impl)

    def process_bind_param(self, value, dialect):
        if value is None or pd.isna(value):
            return None
        return int(value)


class BooleanWithNA(TypeDecorator):
    """
    Хранит булевы колонки с pd.NA или nan, приводя пропуски в None.
    """
    impl = Boolean
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> Optional[bool]:
        logger.debug(f"Processing BooleanWithNA value: {value!r}")
        if pd.isna(value):
            return None
        return bool(value)

    @property
    def python_type(self):
        return bool


