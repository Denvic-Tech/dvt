from __future__ import annotations

from enum import StrEnum


class ReadV3DateTimePrecision(StrEnum):
    NANOSECONDS = "Nanoseconds"
    MICROSECONDS = "Microseconds"
    SECONDS = "Seconds"


def normalize_datetime_precision(
    value: ReadV3DateTimePrecision | str | None,
) -> ReadV3DateTimePrecision:
    if value is None:
        return ReadV3DateTimePrecision.MICROSECONDS
    if isinstance(value, ReadV3DateTimePrecision):
        return value
    normalized_value = str(value).strip().lower()
    aliases = {
        "nanoseconds": ReadV3DateTimePrecision.NANOSECONDS,
        "microseconds": ReadV3DateTimePrecision.MICROSECONDS,
        "seconds": ReadV3DateTimePrecision.SECONDS,
    }
    if normalized_value in aliases:
        return aliases[normalized_value]
    try:
        return ReadV3DateTimePrecision(str(value))
    except ValueError as exc:
        raise ValueError(f"Unsupported read_v3 datetime precision: {value!r}") from exc


def pandas_datetime_dtype(value: ReadV3DateTimePrecision | str | None) -> str:
    precision = normalize_datetime_precision(value)
    return {
        ReadV3DateTimePrecision.NANOSECONDS: "datetime64[ns]",
        ReadV3DateTimePrecision.MICROSECONDS: "datetime64[us]",
        ReadV3DateTimePrecision.SECONDS: "datetime64[s]",
    }[precision]
