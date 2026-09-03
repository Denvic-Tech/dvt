from collections import Counter
from typing import List, Optional, Union, Dict, Sequence, Any

from loguru import logger
from sqlalchemy import (
    BigInteger, Float, Boolean, DateTime, Integer,
    Table, Column, ClauseElement, PrimaryKeyConstraint,
    Dialect, MetaData,
    text, column
)
from sqlalchemy.sql.elements import quoted_name
from sqlalchemy.dialects import mysql as mysql_dialect
from sqlalchemy.dialects import oracle as oracle_dialect
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.type_api import TypeEngine

from core.mapper import type_decorators as td
from core.types import DataType, DBColumn
from core.utils.translit import ru2en
from ._shared import CH_TYPES


ORACLE_DEFAULT_VARCHAR2_LENGTH = 4000


def _get_sqla_type_from_db_column(column: DBColumn, dialect: Dialect, use_jsonb_pg: bool = True) -> TypeEngine:
    """
    Определяет SQLAlchemy-тип на основе метаданных колонки (DBColumn) для заданного dialect.
    """
    dtype = column.dtype
    nullable = column.nullable or False

    is_ch = dialect.name == "clickhouse"

    if dtype == DataType.INT:
        base = BigInteger  # Безопасный выбор по умолчанию, т.к. нет информации о диапазоне
        if is_ch:
            ch_base = CH_TYPES.Int64
            impl = CH_TYPES.Nullable(ch_base) if nullable else ch_base
            return td.IntegerWithNA(impl)
        return td.IntegerWithNA(base) if nullable else base

    if dtype == DataType.FLOAT:
        if is_ch:
            return CH_TYPES.Float64 if not nullable else CH_TYPES.Nullable(CH_TYPES.Float64)
        return td.FloatWithNA() if nullable else Float

    if dtype == DataType.BOOLEAN:
        if is_ch:
            # ClickHouse обычно использует (U)Int8 для булевых значений
            ch_base = CH_TYPES.UInt8
            return CH_TYPES.Nullable(ch_base) if nullable else ch_base
        return td.BooleanWithNA() if nullable else Boolean

    if dtype == DataType.DATETIME:
        if is_ch:
            return td.CHNullableDateTimeWithNA() if nullable else td.CHDateTimeWithNA()
        return td.DateTimeWithNA() if nullable else DateTime

    if dtype == DataType.TIMEDELTA:
        if is_ch:
            base = CH_TYPES.Float64
            underlying = CH_TYPES.Nullable(base) if nullable else base
            return td.TimedeltaAsFloat(underlying)
        return td.TimedeltaAsFloat()

    if dtype == DataType.DICTIONARY:
        if is_ch:
            ch_str = CH_TYPES.String
            ch_dict = CH_TYPES.Array(CH_TYPES.Tuple([ch_str, ch_str]))
            return CH_TYPES.Nullable(ch_dict) if nullable else ch_dict

        if dialect.name == "postgresql":
            pg_json_type = postgresql.JSONB if use_jsonb_pg else postgresql.JSON
            return pg_json_type(none_as_null=nullable)

        if dialect.name in ("mysql", "mariadb"):
            return mysql_dialect.JSON(none_as_null=nullable)

    if dtype in (DataType.STRING, DataType.CATEGORY, DataType.OBJECT, DataType.DICTIONARY):
        if is_ch:
            ch_str = CH_TYPES.String
            return CH_TYPES.Nullable(ch_str) if nullable else ch_str

        if dialect.name == "oracle":
            return oracle_dialect.VARCHAR2(ORACLE_DEFAULT_VARCHAR2_LENGTH)

        return td.StringyType()

    # Fallback для UNKNOWN и других типов
    raise TypeError(f"Неизвестный или неподдерживаемый тип данных: {dtype}")


def build_table_from_db_columns(
        table_name: str,
        columns: List[DBColumn],
        dialect: Dialect,
        metadata: MetaData,
        primary_key_cols: Optional[Union[str, List[str]]] = None,
        partition_by: Optional[Union[str, List[str], ClauseElement]] = None,
        order_by: Optional[Union[str, List[str], ClauseElement]] = None,
        add_surrogate_pk_if_missing: bool = False,
        surrogate_pk_name: str = "id",
        surrogate_pk_type: type[TypeEngine] = Integer,
) -> Table:
    """
    Создает SQLAlchemy Table на основе списка метаданных колонок (DBColumn).

    Эта функция аналогична `build_table_from_df`, но не требует DataFrame,
    а получает схему из переданного списка `columns`.

    Для ASCII-имен колонок исходный регистр сохраняется, не-ASCII имена
    транслитерируются в безопасный lower-case ASCII.

    PRIMARY KEY применяется только при явной передаче `primary_key_cols`.
    """
    ru2en_map: Dict[str, str] = {}
    used: Counter = Counter()
    original_col_names = [c.name for c in columns]

    def _is_ascii(name: str) -> bool:
        return all(ord(ch) < 128 for ch in name)

    for raw in original_col_names:
        eng = raw if _is_ascii(raw) else ru2en(raw)
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

    pk_list: list[str] = []
    if primary_key_cols:
        raw_pk_names = _ensure_list(primary_key_cols)
        found_pk_raw = [name for name in raw_pk_names if isinstance(name, str) and name in original_col_names]
        if len(found_pk_raw) != len(raw_pk_names):
            missing = set(str(x) for x in raw_pk_names) - set(found_pk_raw)
            if missing:
                logger.warning(f"Колонки для PK не найдены в метаданных и будут проигнорированы: {missing}")
        pk_list = [ru2en_map[name] for name in found_pk_raw]

    order_by_in = _ensure_list(order_by)
    partition_by_in = _ensure_list(partition_by)

    def _resolve_column_name(name: str) -> Optional[str]:
        if name in ru2en_map:
            return ru2en_map[name]
        if name in ru2en_map.values():
            return name
        return None

    def _as_identifier_expr(name: str) -> ClauseElement:
        return column(quoted_name(name, True))

    cols: list[Column] = []
    for db_column in columns:
        raw_name = db_column.name
        eng_name = ru2en_map[raw_name]
        sqla_type: TypeEngine = _get_sqla_type_from_db_column(db_column, dialect)
        nullable = db_column.nullable or False

        is_single_pk = (eng_name in pk_list and len(pk_list) == 1)

        if nullable and eng_name in pk_list:
            raise ValueError(f"Колонка '{raw_name}' (→ '{eng_name}') указана как PK, но содержит NULL.")

        autoincrement = True if (is_single_pk and isinstance(sqla_type, Integer)) else None

        cols.append(
            Column(
                eng_name,
                sqla_type,
                primary_key=is_single_pk,
                nullable=nullable,
                autoincrement=autoincrement,
                quote=True,
            )
        )

    if not pk_list and add_surrogate_pk_if_missing:
        logger.info(f"PK не задан — добавляю суррогатный '{surrogate_pk_name}'.")
        cols.append(
            Column(
                surrogate_pk_name,
                surrogate_pk_type,
                primary_key=True,
                autoincrement=True,
                quote=True,
            )
        )
        pk_list = [surrogate_pk_name]

    table_args: list[Any] = []
    if dialect.name == "clickhouse":
        try:
            from clickhouse_sqlalchemy.engines import MergeTree
        except Exception as e:
            raise ImportError("Для ClickHouse нужен пакет 'clickhouse-sqlalchemy'.") from e

        def _norm_expr_list(items: list[Any]) -> list[Any] | None:
            if not items:
                return None
            out: list[Any] = []
            for it in items:
                if isinstance(it, ClauseElement):
                    out.append(it)
                elif isinstance(it, str):
                    mapped_name = _resolve_column_name(it)
                    if mapped_name is None:
                        out.append(text(it))
                    else:
                        out.append(_as_identifier_expr(mapped_name))
                else:
                    out.append(it)
            return out

        part_expr = _norm_expr_list(partition_by_in)
        order_expr = _norm_expr_list(order_by_in)

        if not order_expr:
            if pk_list:
                order_expr = [_as_identifier_expr(pk_name) for pk_name in pk_list]
                logger.info(f"ClickHouse: order_by не задан, используем PK: {pk_list}")
            else:
                order_expr = [text("tuple()")]
                logger.warning("ClickHouse: ни PK, ни order_by не заданы — устанавливаю ORDER BY tuple().")

        pk_expr = [_as_identifier_expr(pk_name) for pk_name in pk_list] if pk_list else None

        engine_opts = MergeTree(
            partition_by=part_expr[0] if part_expr and len(part_expr) == 1 else (
                tuple(part_expr) if part_expr else None),
            order_by=order_expr[0] if len(order_expr) == 1 else tuple(order_expr),
            primary_key=pk_expr[0] if pk_expr and len(pk_expr) == 1 else (tuple(pk_expr) if pk_expr else None),
        )
        table_args.append(engine_opts)

    if len(pk_list) > 1:
        table_args.append(PrimaryKeyConstraint(*pk_list, name=f"{table_name}_pk"))

    table = Table(table_name, metadata, *cols, *table_args, extend_existing=True)
    setattr(table, "rename_map", ru2en_map)

    return table
