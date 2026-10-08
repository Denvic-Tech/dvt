from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..entities import Dataset
from ..types import CheckErrorKind, Freshness


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _failure_freshness(dataset: Dataset) -> Freshness:
    if dataset.last_check_error_kind is CheckErrorKind.NOT_FOUND:
        return Freshness.NOT_FOUND
    return Freshness.UNREACHABLE


def compute_freshness(dataset: Dataset, *, ttl_seconds: int, now: datetime) -> Freshness:
    """Свежесть схемы: последняя неудачная проверка побеждает более старую синхронизацию.

    `not_found` означает, что источник ответил, но объявленных базы или таблицы в нём нет,
    то есть локатор ноды в графе устарел.
    """
    synced_at = dataset.schema_synced_at
    failed_at = dataset.last_check_failed_at

    if synced_at is None:
        return _failure_freshness(dataset) if failed_at is not None else Freshness.UNVERIFIED

    synced = _aware(synced_at)
    if failed_at is not None and _aware(failed_at) > synced:
        return _failure_freshness(dataset)
    if _aware(now) - synced > timedelta(seconds=ttl_seconds):
        return Freshness.STALE
    return Freshness.FRESH
