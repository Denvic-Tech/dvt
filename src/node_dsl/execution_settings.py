from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Self


class ExecutionDateTimePrecision(StrEnum):
    NANOSECONDS = "Nanoseconds"
    MICROSECONDS = "Microseconds"
    SECONDS = "Seconds"


@dataclass(frozen=True)
class ExecutionSettings:
    datetime_precision: ExecutionDateTimePrecision = ExecutionDateTimePrecision.MICROSECONDS

    @classmethod
    def from_app_runtime_settings(cls, runtime_settings: Any) -> Self:
        raw_precision = getattr(runtime_settings, "datetime_precision", None)
        if raw_precision is None:
            return cls()
        return cls(datetime_precision=cls._coerce_datetime_precision(raw_precision))

    @staticmethod
    def _coerce_datetime_precision(value: Any) -> ExecutionDateTimePrecision:
        if isinstance(value, ExecutionDateTimePrecision):
            return value
        raw_value = getattr(value, "value", value)
        if raw_value == "Milliseconds":
            raw_value = ExecutionDateTimePrecision.MICROSECONDS.value
        normalized_value = str(raw_value).strip().lower()
        aliases = {
            "nanoseconds": ExecutionDateTimePrecision.NANOSECONDS,
            "microseconds": ExecutionDateTimePrecision.MICROSECONDS,
            "seconds": ExecutionDateTimePrecision.SECONDS,
        }
        if normalized_value in aliases:
            return aliases[normalized_value]
        try:
            return ExecutionDateTimePrecision(str(raw_value))
        except ValueError as exc:
            raise ValueError(f"Unsupported execution datetime precision: {value!r}") from exc
