"""Operation schemas and adapters for built-in column transformations."""

import re
from functools import partial
from typing import Any, Literal

import pandas as pd
from pydantic import Field, model_validator

from src.node_dsl.node_mixins.column_rules import ColumnRuleOperation, RuleModel

from .column_operations import transform_column


class Replacement(RuleModel):
    old: str | int | float | bool | None
    new: str | int | float | bool | None


class ReplaceParams(RuleModel):
    pairs: list[Replacement] = Field(min_length=1)
    legacy_dictionary: dict[str, Any] | None = None

    @model_validator(mode="after")
    def unique_keys(self):
        keys = [(type(pair.old).__name__, pair.old) for pair in self.pairs]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate replacement keys")
        return self


class RegexParams(RuleModel):
    pattern: str = Field(min_length=1)
    replacement: str = ""

    @model_validator(mode="after")
    def valid_regex(self):
        compiled = re.compile(self.pattern)
        compiled.sub(self.replacement, "")
        return self


class TimezoneParams(RuleModel):
    timezone: str = "Europe/Moscow"

    @model_validator(mode="after")
    def valid_timezone(self):
        pd.Timestamp("2026-01-01").tz_localize(self.timezone)
        return self


class PeriodParams(RuleModel):
    period: Literal["month", "week", "year", "day", "hour", "minute", "second"] = "month"


class DeltaParams(RuleModel):
    years: int = 0
    months: int = 0
    days: int = 0
    hours: int = 0
    minutes: int = 0
    seconds: int = 0


class SplitParams(RuleModel):
    delimiter: str = Field(min_length=1)
    max_splits: int = Field(default=1, ge=1, le=1000)
    drop_source: bool = False


class ExpressionParams(RuleModel):
    expression: str = Field(min_length=1)


PARAM_MODELS = {
    "replace": ReplaceParams,
    "regex": RegexParams,
    "timezone": TimezoneParams,
    "period": PeriodParams,
    "delta": DeltaParams,
    "split": SplitParams,
    "expression": ExpressionParams,
}


def split_targets(source, params):
    return [f"{source}_{index + 1}" for index in range(params.max_splits + 1)]


OPERATIONS = {
    name: ColumnRuleOperation(
        params_model=model,
        transform=partial(transform_column, operation=name),
        compatible_kinds=("datetime",) if name == "delta" else (),
        compatibility_kinds=("datetime", "timedelta") if name == "delta" else (),
        expanded_targets=split_targets if name == "split" else None,
        drops_source=(lambda params: params.drop_source) if name == "split" else None,
    )
    for name, model in PARAM_MODELS.items()
}
