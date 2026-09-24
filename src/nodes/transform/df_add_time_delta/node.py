from datetime import timedelta

import pandas as pd
from dask import dataframe as dd
from src.node_dsl import BaseNode, InputField, OutputField, NodeValidationError, DFOutputBaseNode

from src.node_dsl.hooks import on_validation
from src.node_dsl.node_typing import IO


class AddTimeDeltaToDataFrame(DFOutputBaseNode):
    TITLE = "Add TimeDelta To Dataframe"
    ICON_KEY = "add-timedelta-to-dataframe"
    EMOJI = "⏳"
    CATEGORY = "Transform"

    df: dd.DataFrame = InputField(
        agent_description=(
            "Connect a DataFrame with a verified temporal source column. This node applies a "
            "pandas calendar DateOffset, not a fixed elapsed-time timedelta; test month-end and "
            "timezone cases."
        ),
    )
    column_with_time: IO.COLUMN_NAME = InputField(
        agent_description=(
            "Choose an existing datetime/timedelta-typed column; strings must be converted first. "
            "Although validation accepts timedelta, verify the chosen calendar offset is supported "
            "by the actual values."
        ),
    )
    new_column_with_time: str = InputField(
        agent_description=(
            "Choose the result field name. An existing name is overwritten; use a new name when "
            "the original timestamp must be preserved."
        ),
    )

    years: float = InputField(
        agent_description=(
            "Set the signed calendar-year offset. The runtime converts this value to int, "
            "discarding fractional years; check leap-day results."
        ),
        default=0.0,
    )
    months: float = InputField(
        agent_description=(
            "Set the signed calendar-month offset, not an assumed 30-day duration. Fractional "
            "months are discarded by int conversion; verify month-end behavior."
        ),
        default=0.0,
    )
    days: float = InputField(
        agent_description=(
            "Set signed calendar days; fractions are discarded by int conversion. Check local-time "
            "behavior if timestamps carry a timezone."
        ),
        default=0.0,
    )
    seconds: float = InputField(
        agent_description=(
            "Set the signed seconds component of the calendar DateOffset. The runtime converts it "
            "to an integer, so do not use fractional seconds for subsecond precision."
        ),
        default=0.0,
    )
    microseconds: float = InputField(
        agent_description=(
            "This exposed field is currently not passed to DateOffset and has no effect. Do not "
            "rely on it for subsecond shifts; use a supported alternative."
        ),
        default=0.0,
    )
    milliseconds: float = InputField(
        agent_description=(
            "This exposed field is currently ignored by the implementation. Do not claim a "
            "millisecond offset was applied."
        ),
        default=0.0,
    )
    minutes: float = InputField(
        agent_description=(
            "Set the signed minute component of the DateOffset. Fractions are truncated to "
            "integers and combine with the other applied components."
        ),
        default=0.0,
    )
    hours: float = InputField(
        agent_description=(
            "Set the signed hour component. Fractions are discarded; verify timezone/DST behavior "
            "when calendar and time components are combined."
        ),
        default=0.0,
    )
    weeks: float = InputField(
        agent_description=(
            "This exposed field is currently not applied. Express an intended whole-week calendar "
            "shift through days (7 per week) or choose an appropriate supported node."
        ),
        default=0.0,
    )

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
