from datetime import timedelta

import pandas as pd
from dask import dataframe as dd
from src.node_dsl import BaseNode, InputField, OutputField, NodeValidationError, DFOutputBaseNode

from src.node_dsl.hooks import on_validation
from src.node_dsl.node_typing import IO


class AddTimeDeltaToDataFrame(DFOutputBaseNode):
    TITLE = "Add TimeDelta To Dataframe"
    EMOJI = "⏳"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField()
    column_with_time: IO.COLUMN_NAME = InputField()
    new_column_with_time: str = InputField()

    years: float = InputField(default=0.0)
    months: float = InputField(default=0.0)
    days: float = InputField(default=0.0)
    seconds: float = InputField(default=0.0)
    microseconds: float = InputField(default=0.0)
    milliseconds: float = InputField(default=0.0)
    minutes: float = InputField(default=0.0)
    hours: float = InputField(default=0.0)
    weeks: float = InputField(default=0.0)

    output: dd.DataFrame = OutputField()

    @on_validation
    def validation_column_existing(self):
        """Проверяет, входит ли колонка в DataFrame """
        if not (self.column_with_time in self.df.columns):
            raise NodeValidationError(f'{self.column_with_time} not in {self.df.columns}')

    @on_validation
    def validation_column_type(self):
        """Проверяет, является ли Column временным полем (datetime, timedelta)"""
        if not (
                pd.api.types.is_datetime64_any_dtype(self.df[self.column_with_time]) or
                pd.api.types.is_timedelta64_dtype(self.df[self.column_with_time])):
            raise NodeValidationError(f"Input column {self.column_with_time} is not a datetime64 or timedelta64 dtype")


    def process(self):
        # Создаем объект смещения Pandas
        # Он корректно обработает календарную логику (високосные года, разную длину месяцев)
        offset = pd.DateOffset(
            years=int(self.years),
            months=int(self.months),
            days=int(self.days),
            hours=int(self.hours),
            minutes=int(self.minutes),
            seconds=int(self.seconds)
        )

        if isinstance(self.df, dd.DataFrame):
            series = self.df[self.column_with_time]
            self.df[self.new_column_with_time] = series.map_partitions(
                lambda s: s + offset,
                meta=series._meta,
            )
        else:
            self.df[self.new_column_with_time] = self.df[self.column_with_time] + offset

        self.output = self.df
