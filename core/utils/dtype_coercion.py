from typing import Any

import pandas as pd
from loguru import logger


def _coerce_to_bool(series: pd.Series) -> pd.Series:
    """
    Универсальное приведение к bool из строк/чисел.
    Поддерживает '0', '1', 'true', 'false', None, NaN, 0, 1.
    Возвращает pandas.BooleanDtype() (nullable).
    """
    # Если всё уже bool-like — просто вернуть
    if pd.api.types.is_bool_dtype(series):
        return series

    # Универсальное преобразование
    try:
        return series.map(
            lambda x: (
                True if str(x).strip().lower() in ("1", "true", "t", "yes", "y")
                else False if str(x).strip().lower() in ("0", "false", "f", "no", "n")
                else pd.NA
            )
        ).astype("boolean")
    except Exception:
        return series.astype("boolean", errors="ignore")


def apply_dtypes_and_casts(
    df: pd.DataFrame,
    dtype_map: dict[str, Any],
    tz_cols: list[str],
    naive_dt_cols: list[str],
) -> pd.DataFrame:
    """
    Безопасно приводит типы колонок DataFrame к тем, что ожидает meta_df.
    """
    for col, target_dtype in dtype_map.items():
        if col not in df.columns:
            continue

        # --- 🕒 Datetime ---
        if col in tz_cols:
            parsed = pd.to_datetime(df[col], utc=True, errors="coerce")
            # Keep nanosecond precision to avoid Dask meta mismatches (us vs ns).
            df[col] = parsed.astype("datetime64[ns, UTC]")
            continue
        if col in naive_dt_cols:
            parsed = pd.to_datetime(df[col], errors="coerce")
            if pd.api.types.is_datetime64_any_dtype(parsed.dtype):
                parsed = parsed.astype("datetime64[ns]")
            df[col] = parsed
            continue

        # --- 🔢 Числа ---
        if pd.api.types.is_integer_dtype(target_dtype):
            df[col] = pd.to_numeric(df[col], errors="coerce", downcast="integer")
            continue
        if pd.api.types.is_float_dtype(target_dtype):
            df[col] = pd.to_numeric(df[col], errors="coerce", downcast="float")
            continue

        # --- ✅ Boolean ---
        if pd.api.types.is_bool_dtype(target_dtype):
            df[col] = _coerce_to_bool(df[col])
            continue

        # --- 🧾 Categorical / Enum ---
        if pd.api.types.is_bool_dtype(target_dtype):
            df[col] = df[col].astype("category", errors="ignore")
            continue

        # --- 🧶 String ---
        if pd.api.types.is_string_dtype(target_dtype):
            if not pd.api.types.is_string_dtype(df[col].dtype):
                df[col] = df[col].astype("string")
            continue

        # --- fallback ---
        try:
            df[col] = df[col].astype(target_dtype)
        except Exception as e:
            logger.debug(f"[coerce] Fallback to object for {col}: {e}")
            df[col] = df[col].astype("object")

    return df
