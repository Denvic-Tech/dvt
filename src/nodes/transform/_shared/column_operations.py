"""Operations used by the shared rule planner (all expressions stay lazy)."""

import re

import dask.dataframe as dd
import pandas as pd

from src.node_dsl.node_mixins.column_rules import PlannedColumn, column_kind


def _coerce(value, dtype):
    if value is None:
        return None
    kind = column_kind(dtype)
    if kind == "datetime":
        value = pd.Timestamp(value)
        tz = getattr(dtype, "tz", None)
        if tz is not None:
            return value.tz_localize(tz) if value.tz is None else value.tz_convert(tz)
        return value.tz_localize(None) if value.tz is not None else value
    if kind == "number":
        return int(float(value)) if pd.api.types.is_integer_dtype(dtype) else float(value)
    if kind == "boolean":
        if value in (True, False, 0, 1):
            return bool(value)
        if str(value).lower() in ("true", "false"):
            return str(value).lower() == "true"
        raise ValueError(f"Not a boolean: {value!r}")
    if kind == "text":
        return str(value)
    return value


def replace_pairs(series, pairs):
    dtype = series.dtype
    prepared = []
    force_text = False
    for pair in pairs:
        old_value = pair["old"] if isinstance(pair, dict) else pair.old
        new_value = pair["new"] if isinstance(pair, dict) else pair.new
        try:
            old = _coerce(old_value, dtype)
        except (ValueError, TypeError, OverflowError):
            old = old_value
        try:
            new = _coerce(new_value, dtype)
        except (ValueError, TypeError, OverflowError):
            new = str(new_value)
            force_text = True
        if any(old == previous or (old is None and previous is None) for previous, _ in prepared):
            raise ValueError("Replacement keys collide after conversion to column dtype")
        prepared.append((old, new))
    output_dtype = dtype
    if force_text or isinstance(dtype, pd.CategoricalDtype):
        output_dtype = pd.StringDtype()
    elif any(new is None for _, new in prepared):
        if pd.api.types.is_integer_dtype(dtype):
            output_dtype = "UInt64" if pd.api.types.is_unsigned_integer_dtype(dtype) else "Int64"
        elif pd.api.types.is_bool_dtype(dtype):
            output_dtype = "boolean"

    def replace(partition):
        result = partition.astype(output_dtype)
        for old, new in prepared:
            mask = partition.isna() if old is None else partition.eq(old).fillna(False)
            value = (
                str(new) if new is not None and isinstance(output_dtype, pd.StringDtype) else new
            )
            # Match the original values: replacements are simultaneous, never cascading.
            result = result.mask(mask, value)
        return result

    return series.map_partitions(replace, meta=(series.name, output_dtype))


def period_start(series, period, *, compatibility=False):
    if column_kind(series.dtype) != "datetime":
        series = dd.to_datetime(series, errors="coerce")

    def convert(partition):
        if period == "week":
            result = (partition - pd.to_timedelta(partition.dt.weekday, unit="D")).dt.floor("D")
        elif period in ("month", "year"):
            result = partition.dt.normalize().map(
                lambda value: (
                    value
                    if pd.isna(value)
                    else value.replace(
                        **({"day": 1} if period == "month" else {"month": 1, "day": 1})
                    )
                )
            )
        else:
            result = partition.dt.floor(
                {"day": "D", "hour": "h", "minute": "min", "second": "s"}[period]
            )
        result = result.dt.tz_localize(None)
        return result if compatibility else result.astype("datetime64[ns]")

    return series.map_partitions(convert, meta=(series.name, "datetime64[ns]"))


def transform_column(df, item: PlannedColumn, operation: str) -> dict:
    source = item.source
    series = df[source]
    params = item.params
    target = item.targets[0]
    legacy = item.rule.compatibility == "v1"
    if operation == "replace":
        if params.legacy_dictionary is not None:
            from .legacy_replace import replace_legacy

            result = replace_legacy(df, source, params.legacy_dictionary)[source]
        else:
            result = replace_pairs(series, params.pairs)
    elif operation == "regex":
        result = series.astype(str).str.replace(params.pattern, params.replacement, regex=True)
    elif operation == "timezone":
        if column_kind(series.dtype) != "datetime":
            series = dd.to_datetime(series, errors="coerce")

        def set_timezone(partition):
            if partition.dt.tz is None:
                result = partition.dt.tz_localize(
                    params.timezone, ambiguous="NaT", nonexistent="NaT"
                )
            else:
                result = partition.dt.tz_convert(params.timezone)
            return result if legacy else result.astype(f"datetime64[ns, {params.timezone}]")

        result = series.map_partitions(
            set_timezone, meta=(source, f"datetime64[ns, {params.timezone}]")
        )
    elif operation == "period":
        result = period_start(series, params.period, compatibility=legacy)
    elif operation == "delta":
        offset = pd.DateOffset(
            **{
                key: int(getattr(params, key)) if legacy else getattr(params, key)
                for key in ("years", "months", "days", "hours", "minutes", "seconds")
            }
        )
        result = series.map_partitions(lambda part: part + offset, meta=series._meta)
    elif operation == "split":

        def split(partition):
            pieces = partition.astype(str).str.split(
                params.delimiter, n=params.max_splits, expand=True
            )
            pieces = pieces.reindex(columns=range(params.max_splits + 1))
            pieces.columns = item.targets
            return pieces if legacy else pieces.astype("object")

        meta = pd.DataFrame({name: pd.Series(dtype="object") for name in item.targets})
        result = series.map_partitions(split, meta=meta)
        return {name: result[name] for name in item.targets}
    elif operation == "expression":
        if "\x60" in source:
            raise ValueError("Expression column names must not contain backticks")
        # A lexical name token, not a textual macro inside quoted strings.
        expression = re.sub(
            r"""('(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"|\x60[^\x60]*\x60)|\b__column__\b""",
            lambda match: match[1] if match[1] is not None else f"\x60{source}\x60",
            params.expression,
        )
        result = df.eval(expression, engine="python")
        if isinstance(result, dd.DataFrame):
            raise ValueError("Use a value expression, not an assignment")
    else:
        raise ValueError(f"Unknown column operation: {operation}")
    return {target: result}
