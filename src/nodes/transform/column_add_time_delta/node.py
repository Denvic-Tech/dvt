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

    datetime_column: IO.COLUMN = InputField()
    days: float = InputField(default=0.0)
    seconds: float = InputField(default=0.0)
    microseconds: float = InputField(default=0.0)
    milliseconds: float = InputField(default=0.0)
    minutes: float = InputField(default=0.0)
    hours: float = InputField(default=0.0)
    weeks: float = InputField(default=0.0)

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
