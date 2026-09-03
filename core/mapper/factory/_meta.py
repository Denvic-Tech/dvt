from typing import Tuple, Dict, Any, Optional, List

import pandas as pd
import sqlalchemy as sa
from loguru import logger

from core.mapper.sa2pd_types import dtype_from_sqla_type
from core.mapper.sql2sa_types import get_ch_sa_type


def _describe_clickhouse(
        engine: sa.Engine,
        *,
        table_name: Optional[str],
        schema: Optional[str],
        raw_query: Optional[str] = None,
) -> pd.DataFrame:
    """
    DESCRIBE TABLE для ClickHouse.
    Если передан raw_query — делает DESCRIBE TABLE (<query>),
    иначе — DESCRIBE TABLE <schema.table>.
    Возвращает DataFrame со столбцами как в CH: name, type, default_type, ...
    """
    if not (raw_query or table_name):
        raise ValueError("ClickHouse DESCRIBE: укажи table_name или raw_query")

    if raw_query:
        sql = f"DESCRIBE TABLE ({raw_query})"
    else:
        full = f"`{schema}`.`{table_name}`" if schema else f"`{table_name}`"
        sql = f"DESCRIBE TABLE {full}"

    with engine.connect() as conn:
        return pd.read_sql_query(sa.text(sql), conn)


def build_meta_from_schema(
        *,
        engine: sa.Engine,
        table_name: Optional[str],
        schema: Optional[str],
        index_col: str,
        raw_query: Optional[str] = None,  # для CH можно описывать произвольный SELECT
        tz_for_timestamptz: str = "UTC",
        decimal_as_float: bool = True,
        use_string_dtype: bool = True,
        enum_as_category: bool = False,
) -> Tuple[pd.DataFrame, Dict[str, Any], List[str], List[str]]:
    """
    Возвращает кортеж:
      meta_df       — пустой pandas.DataFrame с нужными колонками/индексом и dtypes,
      dtype_map     — {col -> pandas dtype}, чтобы приводить данные после чтения,
      tz_cols       — колонки с tz-aware datetime (если такие есть),
      naive_dt_cols — колонки с naive datetime/date.

    Работает для ClickHouse, PostgreSQL, MSSQL, MySQL/MariaDB, SQLite, Oracle.
    """
    dialect = engine.dialect.name.lower()

    col_names: List[str] = []
    dtype_map: Dict[str, Any] = {}
    tz_cols: List[str] = []
    naive_dt_cols: List[str] = []

    if dialect == "clickhouse":
        # Для CH берём точные типы через DESCRIBE (поддерживает и SELECT)
        df_desc = _describe_clickhouse(
            engine,
            table_name=table_name,
            schema=schema,
            raw_query=raw_query,
        )
        if "name" not in df_desc.columns or "type" not in df_desc.columns:
            raise RuntimeError("ClickHouse DESCRIBE не вернул столбцы 'name'/'type'")

        for _, row in df_desc.iterrows():
            name = str(row["name"])
            raw_type = str(row["type"])
            nullable = "Nullable(" in raw_type

            # Преобразуем строковый CH-тип в SQLAlchemy-тип (из твоего sql2sa_types)
            sa_type = get_ch_sa_type(raw_type)

            # Маппим в pandas dtype + флаги (из твоего sa2pd_types)
            pd_dtype, is_tz, is_naive = dtype_from_sqla_type(
                sa_type,
                nullable=nullable,
                dialect_name=dialect,
                tz_for_timestamptz=tz_for_timestamptz,
                decimal_as_float=decimal_as_float,
                use_string_dtype=use_string_dtype,
                enum_as_category=enum_as_category,
            )

            col_names.append(name)
            dtype_map[name] = pd_dtype
            if is_tz:
                tz_cols.append(name)
            if is_naive:
                naive_dt_cols.append(name)

    else:
        # Для остальных — обычная рефлексия таблицы через SA Inspector
        if not table_name:
            raise ValueError("Для диалекта '{dialect}' обязан быть указан table_name")

        insp = sa.inspect(engine)
        cols = insp.get_columns(table_name, schema=schema)
        if not cols:
            # fallback через MetaData если что-то пошло не так
            metadata = sa.MetaData(schema=schema)
            table = sa.Table(table_name, metadata, autoload_with=engine, schema=schema)
            cols = [{"name": c.name, "type": c.type, "nullable": c.nullable} for c in table.columns]  # type: ignore

        for c in cols:
            name = c["name"]
            col_type = c["type"]  # SQLAlchemy type
            nullable = bool(c.get("nullable", True))

            pd_dtype, is_tz, is_naive = dtype_from_sqla_type(
                col_type,
                nullable=nullable,
                dialect_name=dialect,
                tz_for_timestamptz=tz_for_timestamptz,
                decimal_as_float=decimal_as_float,
                use_string_dtype=use_string_dtype,
                enum_as_category=enum_as_category,
            )

            col_names.append(name)
            dtype_map[name] = pd_dtype
            if is_tz:
                tz_cols.append(name)
            if is_naive:
                naive_dt_cols.append(name)

    # Собираем «пустой» meta_df с нужными dtypes
    meta_df = pd.DataFrame(columns=col_names)
    for name, pd_dtype in dtype_map.items():
        try:
            meta_df[name] = pd.Series([], dtype=pd_dtype)
        except Exception as e:
            logger.debug(f"Не удалось установить dtype для {name} -> {pd_dtype}: {e}")
            meta_df[name] = pd.Series([], dtype="object")

    # Индекс
    if index_col in meta_df.columns:
        meta_df = meta_df.set_index(index_col)

    return meta_df, dtype_map, tz_cols, naive_dt_cols
