from __future__ import annotations

from datetime import date, datetime, timedelta

DateLike = date | datetime


def floor_to_granularity(value: DateLike, granularity: str) -> DateLike:
    if isinstance(value, datetime):
        if granularity == "hour":
            return value.replace(minute=0, second=0, microsecond=0)
        if granularity == "day":
            return value.replace(hour=0, minute=0, second=0, microsecond=0)
        if granularity == "month":
            return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if granularity == "year":
            return value.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return value

    if granularity == "month":
        return value.replace(day=1)
    if granularity == "year":
        return value.replace(month=1, day=1)
    return value


def advance_granularity(value: DateLike, granularity: str) -> DateLike:
    if isinstance(value, datetime):
        if granularity == "hour":
            return value + timedelta(hours=1)
        if granularity == "day":
            return value + timedelta(days=1)
        if granularity == "week":
            return value + timedelta(days=7)
        if granularity == "month":
            month = value.month + 1
            year = value.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            return value.replace(year=year, month=month, day=1)
        if granularity == "year":
            return value.replace(year=value.year + 1, month=1, day=1)
        return value + timedelta(days=1)

    if granularity == "week":
        return value + timedelta(days=7)
    if granularity == "month":
        month = value.month + 1
        year = value.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        return value.replace(year=year, month=month, day=1)
    if granularity == "year":
        return value.replace(year=value.year + 1, month=1, day=1)
    return value + timedelta(days=1)
