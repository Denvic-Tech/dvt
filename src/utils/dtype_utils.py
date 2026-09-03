import pandas as pd
from pandas.api.types import (
    is_numeric_dtype,
    is_datetime64_any_dtype,
    is_bool_dtype,
)

from src.logger import logger


def convert_scalar_to_dtype(v, dtype):
    """Привести одиночное значение к dtype колонки (без Dask-операций)."""
    try:
        if v is None:
            return None

        if is_numeric_dtype(dtype):
            return pd.to_numeric([v], errors="raise")[0]

        if is_datetime64_any_dtype(dtype):
            # Парсим как naive datetime (без часового пояса)
            ts = pd.to_datetime([v], errors="raise")[0]

            # Проверяем, требует ли dtype колонки часовой пояс
            if hasattr(dtype, 'tz'):
                if dtype.tz is not None:
                    # Колонка требует часовой пояс - локализуем
                    if ts.tz is None:
                        # Если колонка с часовым поясом, а значение без - добавляем UTC
                        ts = ts.tz_localize('UTC')
                else:
                    # Колонка без часового пояса - убираем часовой пояс если есть
                    if ts.tz is not None:
                        ts = ts.tz_convert(None)
            elif ts.tz is not None:
                # Если у значения есть часовой пояс, а у dtype нет информации
                ts = ts.tz_convert(None)

            return ts

        if is_bool_dtype(dtype):
            if isinstance(v, str):
                return v.strip().lower() in {"true", "1", "yes", "y"}

            return bool(v)

        return v

    except Exception as e:
        logger.warning(f"Could not convert value={v} to dtype={dtype}: {e}. Using original value.")
        return v


def parse_csv_or_list(v):
    """Преобразовать строку 'a, b, c' -> ['a','b','c'] или оставить список как есть."""
    if isinstance(v, (list, tuple, set)):
        return list(v)

    return [x.strip() for x in str(v).split(",") if x.strip() != ""]


def convert_list_to_dtype(v_list, dtype):
    """Привести список значений к dtype колонки (каждый элемент отдельно)."""
    out = []
    for item in parse_csv_or_list(v_list):
        out.append(convert_scalar_to_dtype(item, dtype))

    return out
