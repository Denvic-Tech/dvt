import decimal
import re
import traceback
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import pandas as pd
import pyarrow as pa


class DataType(StrEnum):
    """Типы данных, поддерживаемые для колонок DataFrame в метаданных."""
    INT = "INT"
    FLOAT = "FLOAT"
    STRING = "STRING"
    BOOLEAN = "BOOLEAN"
    DATETIME = "DATETIME"
    TIMEDELTA = "TIMEDELTA"
    CATEGORY = "CATEGORY"
    DICTIONARY = "DICTIONARY"  # Для словарей, если они представлены в DataFrame
    OBJECT = "OBJECT"          # Общий тип для смешанных или неизвестных данных
    UNKNOWN = "UNKNOWN"
    BINARY = "BINARY"
    LIST = "LIST"
    STRUCT = "STRUCT"

    @classmethod
    def from_type(cls, dtype: Any) -> 'DataType':
        """Преобразует любой type или строковое описание SQL-типа в DataType."""
        try:
            arrow = dtype.pyarrow_dtype if isinstance(dtype, pd.ArrowDtype) else dtype
            if isinstance(arrow, pa.DataType):
                if (pa.types.is_binary(arrow) or pa.types.is_large_binary(arrow)
                        or pa.types.is_fixed_size_binary(arrow)):
                    return cls.BINARY
                if (pa.types.is_list(arrow) or pa.types.is_large_list(arrow)
                        or pa.types.is_fixed_size_list(arrow)):
                    return cls.LIST
                if pa.types.is_struct(arrow):
                    return cls.STRUCT
            if dtype is bytes:
                return cls.BINARY
            # --- 1️⃣ Обработка строковых SQL / ClickHouse типов ---
            if isinstance(dtype, str):
                dtype_low = dtype.lower().strip()

                dtype_low = re.sub(r"nullable\s*\((.*?)\)", r"\1", dtype_low)

                # --- Специальная обработка уточненных типов Oracle ---
                if "oracle_integer" in dtype_low:
                    return cls.INT
                if "oracle_float" in dtype_low:
                    return cls.FLOAT

                # --- Обработка стандартных префиксов oracledb ---
                if dtype_low.startswith("db_type_"):
                    if "number" in dtype_low: return cls.FLOAT
                    if "char" in dtype_low or "clob" in dtype_low: return cls.STRING
                    if "date" in dtype_low or "timestamp" in dtype_low: return cls.DATETIME
                    if "boolean" in dtype_low: return cls.BOOLEAN

                if dtype_low.startswith("number"):
                    match = re.search(r"\((\d+)(?:\s*,\s*(\d+))?\)", dtype_low)
                    if match is not None:
                        scale = match.group(2)
                        if scale is None or int(scale) == 0:
                            return cls.INT
                    return cls.FLOAT

                if dtype_low.startswith(("list<", "large_list<", "fixed_size_list<")):
                    return cls.LIST
                if dtype_low.startswith("struct<"):
                    return cls.STRUCT
                if dtype_low in {"binary[pyarrow]", "large_binary[pyarrow]"}:
                    return cls.BINARY
                if "int" in dtype_low:
                    return cls.INT
                if any(token in dtype_low for token in ("decimal", "float", "double", "real", "numeric")):
                    return cls.FLOAT
                if any(
                    token in dtype_low
                    for token in ("varchar", "char", "clob", "text", "string", "uniqueidentifier", "binary", "varbinary")
                ):
                    return cls.STRING
                if "bool" in dtype_low:
                    return cls.BOOLEAN
                if "date" in dtype_low and "datetime" not in dtype_low:
                    return cls.DATETIME  # можно вернуть DATE, если добавишь в enum
                if "datetime" in dtype_low or "timestamp" in dtype_low:
                    return cls.DATETIME
                if "interval" in dtype_low or "timedelta" in dtype_low:
                    return cls.TIMEDELTA
                if "dict" in dtype_low or "json" in dtype_low:
                    return cls.DICTIONARY
                if "enum" in dtype_low or "category" in dtype_low:
                    return cls.CATEGORY
                return cls.UNKNOWN

            # --- 2️⃣ Python-типы ---
            if dtype is decimal.Decimal:
                return cls.FLOAT
            if dtype is datetime or dtype is date:
                return cls.DATETIME
            if dtype is UUID:
                return cls.STRING
            if dtype is dict:
                return cls.DICTIONARY
            if dtype is object:
                return cls.OBJECT

            # --- 3️⃣ Pandas / NumPy типы ---
            if pd.api.types.is_integer_dtype(dtype):
                return cls.INT
            elif pd.api.types.is_float_dtype(dtype):
                return cls.FLOAT
            elif pd.api.types.is_bool_dtype(dtype):
                return cls.BOOLEAN
            elif pd.api.types.is_datetime64_any_dtype(dtype):
                return cls.DATETIME
            elif pd.api.types.is_timedelta64_dtype(dtype):
                return cls.TIMEDELTA
            elif isinstance(dtype, pd.CategoricalDtype):
                return cls.CATEGORY
            elif pd.api.types.is_string_dtype(dtype):
                return cls.STRING
            elif pd.api.types.is_object_dtype(dtype):
                return cls.OBJECT
            else:
                return cls.UNKNOWN

        except Exception:
            traceback.print_exc()
            return cls.UNKNOWN
