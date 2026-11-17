import pytest

from src.modules.data_catalog.domain import (
    DB_TABLE_KIND,
    DatasetLocator,
    UnknownSourceKindError,
    db_table_locator,
    default_registry,
)
from src.modules.data_catalog.domain.policies import DbTableAdapter, SourceKindRegistry


def test_default_registry_contains_only_db_tables():
    registry = default_registry()
    assert registry.kinds() == (DB_TABLE_KIND,)
    assert isinstance(registry.get(DB_TABLE_KIND), DbTableAdapter)


def test_unknown_kind_is_rejected_and_duplicates_are_refused():
    registry = default_registry()
    with pytest.raises(UnknownSourceKindError):
        registry.get("file")
    with pytest.raises(UnknownSourceKindError):
        registry.build_key(DatasetLocator(kind="file", parts={"path": "a.parquet"}))
    with pytest.raises(ValueError):
        SourceKindRegistry((DbTableAdapter(), DbTableAdapter()))


def test_registry_dispatches_key_and_description_to_the_kind_adapter():
    registry = default_registry()
    locator = db_table_locator("postgresql", "DB", 5432, "Main", "public", "Orders")

    assert registry.build_key(locator) == "postgresql://db:5432/main/public/orders"
    assert registry.describe(locator) == "Main.public.Orders @ DB:5432"


def test_db_table_observation_matching_is_case_insensitive_and_lenient_without_table():
    adapter = default_registry().get(DB_TABLE_KIND)
    locator = db_table_locator("postgresql", "db", 5432, "main", "public", "Orders")

    assert adapter.matches_observation(locator, {"table": "ORDERS"}) is True
    assert adapter.matches_observation(locator, {"table": "customers"}) is False
    assert adapter.matches_observation(locator, {}) is True


def test_locator_requires_kind_and_copies_parts():
    parts = {"table": "t"}
    locator = DatasetLocator(kind="x", parts=parts)
    parts["table"] = "changed"
    assert locator.get("table") == "t"
    with pytest.raises(ValueError):
        DatasetLocator(kind=" ")
