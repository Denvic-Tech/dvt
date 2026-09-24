from datetime import timedelta
from dask import dataframe as dd
from src.node_dsl import BaseNode, InputField, OutputField, NodeValidationError
import pandas as pd

from src.node_dsl.hooks import on_validation
from src.node_dsl.node_typing import IO


class ColumnAddTimeDelta(BaseNode):
    TITLE = "Add TimeDelta To Column"
    EMOJI = "⏳"
    CATEGORY = "Transform"
    EXPERIMENTAL = True

    datetime_column: IO.COLUMN = InputField(
        agent_description=(
            "Experimental Series operation: connect a datetime/timedelta column with known index "
            "alignment. It adds a fixed datetime.timedelta; it does not implement calendar months "
            "or years."
        ),
    )
    days: float = InputField(
        agent_description=(
            "Set signed elapsed days, which combine with other timedelta components. Fractional "
            "values are accepted; use calendar-offset behavior instead if month-end rules are "
            "required."
        ),
        default=0.0,
    )
    seconds: float = InputField(
        agent_description=(
            "Set signed seconds in the elapsed-time offset. Combine deliberately with minute/hour "
            "components to avoid counting the same duration twice."
        ),
        default=0.0,
    )
    microseconds: float = InputField(
        agent_description=(
            "Set the signed microsecond component; verify the downstream timestamp precision does "
            "not discard it."
        ),
        default=0.0,
    )
    milliseconds: float = InputField(
        agent_description=(
            "Set the signed millisecond component of the elapsed-time offset, not a timestamp "
            "value."
        ),
        default=0.0,
    )
    minutes: float = InputField(
        agent_description=(
            "Set signed elapsed minutes; all configured duration components are added together."
        ),
        default=0.0,
    )
    hours: float = InputField(
        agent_description=(
            "Set signed elapsed hours. Check expected results around daylight-saving transitions "
            "rather than assuming calendar-day semantics."
        ),
        default=0.0,
    )
    weeks: float = InputField(
        agent_description=(
            "Set signed weeks, each equal to seven elapsed days in timedelta. This is not a "
            "business-week/calendar scheduling rule."
        ),
        default=0.0,
    )

    output: dd.Series = OutputField()

    @on_validation
    def is_temporal_series(self):
        """Проверяет, является ли Series временным полем (datetime, timedelta)"""
        if not (
                pd.api.types.is_datetime64_any_dtype(self.datetime_column.dtype) or
                pd.api.types.is_timedelta64_dtype(self.datetime_column.dtype)):
            raise NodeValidationError(f"Input series {self.datetime_column} is not a datetime64 or timedelta64 dtype")

    def process(self):
        delta = timedelta(
            days=self.days,
            seconds=self.seconds,
            microseconds=self.microseconds,
            milliseconds=self.milliseconds,
            minutes=self.minutes,
            hours=self.hours,
            weeks=self.weeks
        )
        self.output = self.datetime_column + delta
