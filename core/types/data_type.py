import decimal
import traceback
import re
from datetime import datetime, date
from enum import Enum
from typing import Any
from uuid import UUID

import pandas as pd


class DataType(str, Enum):
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

    @classmethod
    def from_type(cls, dtype: Any) -> 'DataType':
        """Преобразует любой type или строковое описание SQL-типа в DataType."""
        try:
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
