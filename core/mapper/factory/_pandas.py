import json
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional, Union, List, Dict, Sequence, TypeVar, Type

import pandas as pd
from loguru import logger
from pandas import PeriodDtype
from pandas.api.types import (
    is_integer_dtype, is_float_dtype, is_bool_dtype, is_datetime64_any_dtype,
    is_string_dtype, is_object_dtype,
    is_timedelta64_dtype, is_complex_dtype
)
from sqlalchemy import (
    text, PrimaryKeyConstraint, Date, ClauseElement, Column,
    Integer, Float, DateTime, Boolean, MetaData, Table,
    BigInteger, Numeric, Text, Dialect, JSON as SA_JSON,
    Sequence, Identity  # Добавлены String и Sequence
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql.type_api import TypeEngine
from sqlalchemy.types import TypeDecorator

from core.mapper import type_decorators as td
from core.utils.translit import ru2en
from ._shared import CH_TYPES, INT32_MAX, INT32_MIN, VARCHAR, PGTimestamp

# Имитация импортов диалектов
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
except Exception:
    oracle_dialect = None

# Константы для Oracle
ORACLE_MAX_VARCHAR_LEN = 4000
DEFAULT_STRING_LEN = 255


def is_nullable_column(column: pd.Series) -> bool:
    return column.isna().any()


def _get_string_length(column: pd.Series, max_limit: int) -> int:
    """Определяет максимальную длину строки в колонке, ограничивая лимитом."""
    non_null = column.dropna().astype(str)
    if non_null.empty:
        return DEFAULT_STRING_LEN
    max_len = int(non_null.str.len().max())
    return min(max_len, max_limit)


def get_sqla_type(column: pd.Series, dialect: Any, use_jsonb_pg: bool = True) -> Any:
    """
    Определяет SQLAlchemy-тип колонки pandas.Series для заданного dialect.
    """
    dtype = column.dtype
    # TODO пока для SQL БД (pg, oracle, и т.д.) делаем все колонки nullable,
    #  т.к. от clickhouse может приходить тип NOT NULL за заполненными ПУСТЫМИ полями
    if dialect != "clickhouse":
        nullable = True
    else:
        nullable = is_nullable_column(column)

    # Проверка доступности ClickHouse типов
    if dialect.name == "clickhouse" and CH_TYPES is None:
        raise ImportError("Для работы с ClickHouse установите 'clickhouse-sqlalchemy'.")

    if dialect.name in ("mysql", "mariadb") and VARCHAR is None:
        raise ImportError("Для работы с MySQL/MariaDB установите 'pymysql' или 'mysqlclient'.")

    # 1) object-dtype
    if is_object_dtype(dtype):
        non_null = column.dropna()
        if non_null.empty:
            if dialect.name in ("mysql", "mariadb"):
                return Text()
            return td.StringyType()

        sample = non_null.iloc[0]

        # Строки
        if isinstance(sample, str):
            if dialect.name == "oracle":
                length = _get_string_length(column, ORACLE_MAX_VARCHAR_LEN)
                if length < ORACLE_MAX_VARCHAR_LEN:
                    return oracle_dialect.VARCHAR2(length)
                else:
                    return oracle_dialect.CLOB()
            if dialect.name in ("mysql", "mariadb"):
                non_null_str = non_null.astype(str)
                max_len = int(non_null_str.str.len().max())
                length = min(max_len, 255)
                return VARCHAR(length)
            if dialect.name == "clickhouse":
                ch_str = CH_TYPES.String
                return CH_TYPES.Nullable(ch_str) if nullable else ch_str
            return td.StringyType()

        # Бинарные
        if isinstance(sample, (bytes, bytearray, memoryview)):
            return td.BytesAsBase64()

        # JSON-подобные (dict/list)
        if isinstance(sample, (dict, list)):
            if dialect.name == "oracle":
                return oracle_dialect.JSON()

            if dialect.name == "postgresql":
                if use_jsonb_pg:
                    return postgresql.JSONB(none_as_null=True)
                return postgresql.JSON(none_as_null=True)

            if dialect.name in ("mysql", "mariadb"):
                return mysql_dialect.JSON()

            if dialect.name == "clickhouse":
                base = CH_TYPES.String
                underlying = CH_TYPES.Nullable(base) if nullable else base

                class CHJsonAsString(TypeDecorator):
                    impl = underlying
                    cache_ok = True

                    def process_bind_param(self, value, _dialect):
                        if value is None or (isinstance(value, float) and pd.isna(value)):
                            return None
                        return json.dumps(value, ensure_ascii=False)

                    def process_result_value(self, value, _dialect):
                        if value is None:
                            return None
                        try:
                            return json.loads(value)
                        except Exception:
                            return value

                return CHJsonAsString()

            return SA_JSON()

        # pandas.Period
        if isinstance(sample, pd.Period):
            return td.PeriodAsDate()

        # datetime/date
        if isinstance(sample, datetime):
            return td.DateTimeWithNA()
        if isinstance(sample, date):
            return Date

        # Decimal
        if isinstance(sample, Decimal):
            return Numeric(38, 10)

        # всё прочее (в т.ч. mix int/str)
        if dialect.name in ("mysql", "mariadb"):
            return Text()
        return td.StringyType()

    # 2) pandas PeriodDtype
    if isinstance(dtype, PeriodDtype):
        return td.PeriodAsDate()

    # 3) pandas IntervalDtype
    if isinstance(dtype, pd.IntervalDtype):
        if dialect.name in ("mysql", "mariadb"):
            return Text()
        return td.StringyType()

    # 4) комплексные
    if is_complex_dtype(dtype):
        if dialect.name in ("mysql", "mariadb"):
            return Text()
        return td.StringyType()

    # 5) категориальные
    if isinstance(dtype, pd.CategoricalDtype):
        if dialect.name in ("mysql", "mariadb"):
            non_null = column.dropna().astype(str)
            max_len = int(non_null.str.len().max()) if not non_null.empty else 255
            length = min(max_len, 255)
            return VARCHAR(length)
        if dialect.name == "oracle":
            return oracle_dialect.VARCHAR2(_get_string_length(column, 255))
        return td.StringyType()

    # 6) StringDtype / Arrow string
    if is_string_dtype(dtype):
        if dialect.name in ("mysql", "mariadb"):
            non_null = column.dropna().astype(str)
            max_len = int(non_null.str.len().max()) if not non_null.empty else 255
            length = min(max_len, 255)
            return VARCHAR(length)
        if dialect.name == "oracle":
            length = _get_string_length(column, ORACLE_MAX_VARCHAR_LEN)
            if length < ORACLE_MAX_VARCHAR_LEN:
                return oracle_dialect.VARCHAR2(length)
            else:
                return oracle_dialect.CLOB()
        if dialect.name == "clickhouse":
            ch_str = CH_TYPES.String
            return CH_TYPES.Nullable(ch_str) if nullable else ch_str
        return td.StringyType()

    # 7) целые
    if is_integer_dtype(dtype):
        # TODO пустые колонки, исправить входные данные, либо сделать обработку
        mx, mn = column.max(skipna=True), column.min(skipna=True)
        if pd.isna(mx) or pd.isna(mn):
            base = Integer
        else:
            base = BigInteger if mx > INT32_MAX or mn < INT32_MIN else Integer
        if dialect.name == "clickhouse":
            ch_base = CH_TYPES.Int64 if base == BigInteger else CH_TYPES.Int32
            impl = CH_TYPES.Nullable(ch_base) if nullable else ch_base
            return td.IntegerWithNA(impl)
        if dialect.name == "oracle":
            if base == BigInteger:
                return oracle_dialect.NUMBER(precision=38, scale=0)
            else:
                return oracle_dialect.NUMBER(precision=10, scale=0)
        return td.IntegerWithNA(base) if nullable else base

    # 8) float
    if is_float_dtype(dtype):
        if dialect.name == "clickhouse":
            return CH_TYPES.Float64 if not nullable else CH_TYPES.Nullable(CH_TYPES.Float64)
        if dialect.name == "oracle":
            return oracle_dialect.BINARY_DOUBLE()
        return td.FloatWithNA() if nullable else Float

    # 9) bool
    if is_bool_dtype(dtype):
        base_type = Boolean
        if dialect.name == "clickhouse":
            return CH_TYPES.UInt8 if not nullable else CH_TYPES.Nullable(CH_TYPES.UInt8)
        if dialect.name == "oracle":
            return oracle_dialect.NUMBER(precision=1, scale=0)
        return td.BooleanWithNA() if nullable else base_type

    # 10) datetime64[*]
    if is_datetime64_any_dtype(dtype):
        if dialect.name == "postgresql":
            if isinstance(dtype, pd.DatetimeTZDtype) and dtype.tz is not None:
                return PGTimestamp(timezone=True)
            return td.DateTimeWithNA() if nullable else DateTime
        if dialect.name == "clickhouse":
            return td.CHNullableDateTimeWithNA() if nullable else td.CHDateTimeWithNA()
        if dialect.name == "oracle":
            return oracle_dialect.TIMESTAMP()
        return td.DateTimeWithNA()

    # 11) timedelta64
    if is_timedelta64_dtype(dtype):
        if dialect.name == "postgresql":
            class IntervalWithNA(TypeDecorator):
                impl = postgresql.INTERVAL
                cache_ok = True

                def process_bind_param(self, value, dialect):
                    if value is None or pd.isna(value):
                        return None
                    if isinstance(value, pd.Timedelta):
                        return value.to_pytimedelta()
                    return value

            return IntervalWithNA()
        if dialect.name == "clickhouse":
            base = CH_TYPES.Float64
            underlying = CH_TYPES.Nullable(base) if nullable else base

            class CHIntervalAsFloat(TypeDecorator):
                impl = underlying
                cache_ok = True

                def process_bind_param(self, value, dialect):
                    if value is None or pd.isna(value):
                        return None
                    return float(value.total_seconds())

            return CHIntervalAsFloat()
        return td.TimedeltaAsFloat()

    # fallback
    base_type = Text
    if dialect.name == "clickhouse" and nullable:
        return CH_TYPES.Nullable(base_type)
    return base_type


def build_table_from_df(
        df: pd.DataFrame,
        table_name: str,
        dialect: Dialect,
        metadata: MetaData,
        primary_key_cols: Optional[Union[str, List[str]]] = None,
        partition_by: Optional[Union[str, List[str], ClauseElement]] = None,
        order_by: Optional[Union[str, List[str], ClauseElement]] = None,
        add_surrogate_pk_if_missing: bool = False,
        surrogate_pk_name: str = "id",
        surrogate_pk_type: type[TypeEngine] = Integer,
        use_jsonb_pg: bool = True,
) -> Table:
    """
    Создает SQLAlchemy Table на основе pandas DataFrame, добавляя
    СУРОГАТНЫЙ первичный ключ, если явный PK не задан или не найден в df.

    Правила именования колонок:
      - Если имя целиком ASCII (латиница/цифры/подчёркивания/прочие ASCII) — оставляем как есть (регистр сохраняется).
      - Иначе: транслитерируем ru2en и приводим к lower-case.

    Для сохранения регистра в DDL у всех колонок включён quote=True.
    """
    if df.index.names and any(n is not None for n in df.index.names):
        df = df.reset_index()

    ru2en_map: Dict[str, str] = {}
    used: Counter = Counter()

    def _is_ascii(s: str) -> bool:
        # Любые ASCII-символы (включая латиницу, цифры, _, - и т.п.)
        # Считаем строку "латиницей", если все codepoint < 128
        return all(ord(ch) < 128 for ch in s)

    # --- Построение карты имён ---
    for raw in df.columns:
        if _is_ascii(raw):
            eng = raw  # латиницу не трогаем (сохраняем регистр)
        else:
            eng = ru2en(raw).lower()  # транслит + lower

        # Гарантия уникальности (case-sensitive, как раньше)
        while eng in ru2en_map.values():
            used[eng] += 1
            eng = f"{eng}_{used[eng]}"
        ru2en_map[raw] = eng

    def _ensure_list(x: Optional[Union[str, Sequence[str], ClauseElement]]) -> list[Any]:
        if x is None:
            return []
        if isinstance(x, (list, tuple)):
            return list(x)
        return [x]

    raw_pk_names = _ensure_list(primary_key_cols)
    found_pk_raw = [name for name in raw_pk_names if isinstance(name, str) and name in df.columns]
    if len(found_pk_raw) != len(raw_pk_names):
        missing = set(str(x) for x in raw_pk_names) - set(found_pk_raw)
        if missing:
            logger.warning(f"Колонки для PK не найдены в DataFrame и будут проигнорированы: {missing}")

    pk_list: list[str] = [ru2en_map[name] for name in found_pk_raw]

    order_by_in = _ensure_list(order_by)
    partition_by_in = _ensure_list(partition_by)

    # ---------- 3) Конструируем столбцы ----------
    cols: list[Column] = []
    for raw_name in df.columns:
        eng_name = ru2en_map[raw_name]
        sqla_type: TypeEngine = get_sqla_type(column=df[raw_name], dialect=dialect, use_jsonb_pg=use_jsonb_pg)
        # TODO пока для SQL БД (pg, oracle, и т.д.) делаем все колонки nullable,
        #  т.к. от clickhouse может приходить тип NOT NULL за заполненными ПУСТЫМИ полями
        if dialect.name != "clickhouse" and eng_name not in pk_list:
            nullable = True
        else:
            nullable = is_nullable_column(df[raw_name])

        # primary_key=True только если PK один (single PK). Для составного добавим PK-constraint ниже.
        is_single_pk = (eng_name in pk_list and len(pk_list) == 1)
        if nullable and eng_name in pk_list:
            raise ValueError(f"Колонка '{raw_name}' (→ '{eng_name}') указана как PK, но содержит NULL.")

        # --- ЛОГИКА ДЛЯ AUTOINCREMENT и GENERATED ID ---
        autoincrement = None
        server_default = None

        # 1. Проверяем, является ли колонка единственным целочисленным PK
        if is_single_pk and isinstance(sqla_type, Integer):
            if dialect.name == "oracle":
                # В Oracle для PK используем Identity Column (GENERATED ALWAYS/BY DEFAULT AS IDENTITY)
                # Это самый надежный способ для работы с пакетной вставкой в Oracle 12c+
                server_default = Identity()
                autoincrement = True

            else:
                # Для остальных диалектов
                autoincrement = True

        cols.append(
            Column(
                eng_name,
                sqla_type,
                primary_key=is_single_pk,
                nullable=nullable,
                autoincrement=autoincrement,
                server_default=server_default,
                quote=True,  # <<< сохраняем точный регистр имён в DDL
            )
        )

    # Если PK не найден и попросили добавить суррогатный — добавим
    if not pk_list and add_surrogate_pk_if_missing:
        logger.info(f"PK не задан — добавляю суррогатный '{surrogate_pk_name}'.")

        # ЛОГИКА ДЛЯ СУРРОГАТНОГО КЛЮЧА
        surr_autoincrement = True
        surr_server_default = None

        if dialect.name == "oracle" and surrogate_pk_type is Integer:
            # Для Oracle используем Identity
            surr_autoincrement = False
            surr_server_default = Identity()

        cols.append(
            Column(
                surrogate_pk_name,
                surrogate_pk_type,
                primary_key=True,
                autoincrement=surr_autoincrement,
                server_default=surr_server_default,  # <-- Добавлен server_default
                quote=True
            )
        )
        pk_list = [surrogate_pk_name]

    if dialect.name == "clickhouse" and CH_TYPES is not None:
        for col in cols:
            col_type = col.type
            if isinstance(col_type, CH_TYPES.DateTime64):
                continue
            if isinstance(col_type, CH_TYPES.Nullable):
                nested = getattr(col_type, "nested_type", None)
                if isinstance(nested, CH_TYPES.DateTime64):
                    continue
                if isinstance(nested, CH_TYPES.DateTime):
                    col.type = CH_TYPES.Nullable(CH_TYPES.DateTime64())
                    continue
            if isinstance(col_type, CH_TYPES.DateTime):
                col.type = CH_TYPES.DateTime64()
                continue
            if isinstance(col_type, DateTime):
                col.type = CH_TYPES.Nullable(CH_TYPES.DateTime64()) if col.nullable else CH_TYPES.DateTime64()
                continue
            if isinstance(col_type, TypeDecorator):
                impl = getattr(col_type, "impl", None)
                if isinstance(impl, DateTime) or (isinstance(impl, type) and issubclass(impl, DateTime)):
                    col.type = CH_TYPES.Nullable(CH_TYPES.DateTime64()) if col.nullable else CH_TYPES.DateTime64()

    # ---------- 4) ClickHouse MergeTree (если нужно) ----------
    table_args: list[Any] = []
    if dialect.name == "clickhouse":
        try:
            # pip install clickhouse-sqlalchemy
            from clickhouse_sqlalchemy.engines import MergeTree
        except Exception as e:
            raise ImportError("Для ClickHouse нужен пакет 'clickhouse-sqlalchemy'.") from e

        # Преобразуем выражения/имена с учётом ru2en_map (c учётом наших правил)
        def _norm_expr_list(items: list[Any]) -> list[Any] | None:
            if not items:
                return None
            out: list[Any] = []
            for it in items:
                if isinstance(it, ClauseElement):
                    out.append(it)
                elif isinstance(it, str):
                    out.append(text(ru2en_map.get(it, it)))
                else:
                    out.append(it)
            return out

        part_expr = _norm_expr_list(partition_by_in)
        order_expr = _norm_expr_list(order_by_in)

        if not order_expr:
            if pk_list:
                order_expr = [text(",".join(pk_list))] if len(pk_list) > 1 else [text(pk_list[0])]
                logger.info(f"ClickHouse: order_by не задан, используем PK: {pk_list}")
            else:
                order_expr = [text("tuple()")]
                logger.warning("ClickHouse: ни PK, ни order_by не заданы — устанавливаю ORDER BY tuple(). "
                               "Это работает, но обычно хуже по производительности.")

        pk_expr = [text(",".join(pk_list))] if len(pk_list) > 1 else ([text(pk_list[0])] if pk_list else None)

        engine_opts = MergeTree(
            partition_by=part_expr[0] if part_expr and len(part_expr) == 1 else (
                tuple(part_expr) if part_expr else None),
            order_by=order_expr[0] if len(order_expr) == 1 else tuple(order_expr),
            primary_key=pk_expr[0] if pk_expr and len(pk_expr) == 1 else (tuple(pk_expr) if pk_expr else None),
        )
        table_args.append(engine_opts)

    # ---------- 5) Составной PK (если нужно) ----------
    if len(pk_list) > 1:
        table_args.append(PrimaryKeyConstraint(*pk_list, name=f"{table_name}_pk"))

    # ---------- 6) Собираем Table ----------
    table = Table(table_name, metadata, *cols, *table_args, extend_existing=True)
    setattr(table, "rename_map", ru2en_map)

    return table


MapperT = TypeVar("MapperT", bound=Type[DeclarativeBase])


def build_mapper_from_df(
        df: pd.DataFrame,
        Base: MapperT,
        table_name: str,
        dialect: Dialect,
        metadata: MetaData,
        primary_key_cols: Optional[Union[str, List[str]]] = 'id',
        partition_by: Optional[Union[str, List[str], ClauseElement]] = None,
        order_by: Optional[Union[str, List[str], ClauseElement]] = None,
        add_surrogate_pk_if_missing: bool = False,
        surrogate_pk_name: str = "id",
        surrogate_pk_type: type[TypeEngine] = Integer,
) -> MapperT:
    """
    Создает класс-маппер SQLAlchemy на основе pandas DataFrame, используя
    двухэтапный (императивный + декларативный) подход для надежной работы с ClickHouse.
    """
    table = build_table_from_df(
        df=df,
        table_name=table_name,
        dialect=dialect,
        metadata=metadata,
        primary_key_cols=primary_key_cols,
        partition_by=partition_by,
        order_by=order_by,
        add_surrogate_pk_if_missing=add_surrogate_pk_if_missing,
        surrogate_pk_name=surrogate_pk_name,
        surrogate_pk_type=surrogate_pk_type,
    )

    ru2en_map = getattr(table, "rename_map", {})

    mapper_properties = {
        raw_name: table.c[eng_name] for raw_name, eng_name in ru2en_map.items()
    }

    def to_dict(self: Any) -> dict:
        return {raw_name: getattr(self, raw_name) for raw_name in ru2en_map.keys()}

    attrs = {
        '__table__': table,
        '__mapper_args__': {
            'properties': mapper_properties
        },
        'to_dict': to_dict,
        'rename_map': ru2en_map
    }

    class_name = "".join(c if c.isalnum() else "_" for c in table_name.capitalize())
    if not class_name or not class_name[0].isalpha():
        class_name = f"MappedTable_{class_name}"

    try:
        MappedClass: type[DeclarativeBase] = type(class_name, (Base,), attrs)
    except Exception as e:
        logger.error(f"Ошибка создания класса-маппера '{class_name}': {e}")
        raise

    return MappedClass
