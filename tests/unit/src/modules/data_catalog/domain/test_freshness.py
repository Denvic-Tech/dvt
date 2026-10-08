from datetime import UTC, datetime, timedelta

from src.modules.data_catalog.domain import CheckErrorKind, Dataset, Freshness, PhysicalLocator
from src.modules.data_catalog.domain.policies import compute_freshness

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def _dataset(**overrides) -> Dataset:
    values = {
        "id": "d",
        "organization_id": "o",
        "locator": PhysicalLocator("postgresql", "h", 5432, "db", "public", "t"),
        "physical_key": "k",
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return Dataset(**values)


def _freshness(dataset: Dataset) -> Freshness:
    return compute_freshness(dataset, ttl_seconds=300, now=NOW)


def test_unverified_fresh_and_stale():
    assert _freshness(_dataset()) is Freshness.UNVERIFIED
    assert _freshness(_dataset(schema_synced_at=NOW - timedelta(seconds=60))) is Freshness.FRESH
    assert _freshness(_dataset(schema_synced_at=NOW - timedelta(seconds=600))) is Freshness.STALE


def test_failure_kind_decides_between_unreachable_and_not_found():
    failed = NOW - timedelta(seconds=10)
    assert _freshness(_dataset(last_check_failed_at=failed)) is Freshness.UNREACHABLE
    assert (
        _freshness(_dataset(last_check_failed_at=failed, last_check_error_kind=CheckErrorKind.NOT_FOUND))
        is Freshness.NOT_FOUND
    )
    # Неудача новее синхронизации побеждает её; старая неудача нет.
    synced = NOW - timedelta(seconds=60)
    assert (
        _freshness(
            _dataset(
                schema_synced_at=synced,
                last_check_failed_at=failed,
                last_check_error_kind=CheckErrorKind.NOT_FOUND,
            )
        )
        is Freshness.NOT_FOUND
    )
    assert (
        _freshness(_dataset(schema_synced_at=synced, last_check_failed_at=NOW - timedelta(seconds=120)))
        is Freshness.FRESH
    )


def test_naive_datetimes_are_treated_as_utc():
    naive = (NOW - timedelta(seconds=60)).replace(tzinfo=None)
    assert _freshness(_dataset(schema_synced_at=naive)) is Freshness.FRESH
