from datetime import UTC, datetime

from src.modules.data_catalog.domain import (
    LINEAGE_SCHEMA_VERSION,
    ProjectCatalogProjection,
    ProjectionStamp,
    ProjectionStatus,
)
from src.modules.data_catalog.domain.policies import is_projection_current, variables_fingerprint


def test_fingerprint_ignores_key_order_and_treats_none_as_empty():
    assert variables_fingerprint({"b": 1, "a": "x"}) == variables_fingerprint({"a": "x", "b": 1})
    assert variables_fingerprint(None) == variables_fingerprint({})
    assert variables_fingerprint({"a": 1}) != variables_fingerprint({"a": 2})


def _projection(*, revision: int, fingerprint: str, depends: bool, status=ProjectionStatus.OK):
    return ProjectCatalogProjection(
        project_id="p",
        organization_id="o",
        stamp=ProjectionStamp(revision, fingerprint, LINEAGE_SCHEMA_VERSION),
        built_at=datetime.now(UTC),
        status=status,
        depends_on_project_variables=depends,
    )


def test_projection_currency_rules():
    current = ProjectionStamp(5, "fp-new", LINEAGE_SCHEMA_VERSION)

    assert is_projection_current(None, current) is False
    assert is_projection_current(_projection(revision=5, fingerprint="fp-new", depends=False), current)
    assert is_projection_current(_projection(revision=4, fingerprint="fp-new", depends=False), current) is False
    # Отпечаток переменных важен только для проекций, зависящих от переменных.
    assert is_projection_current(_projection(revision=5, fingerprint="fp-old", depends=False), current)
    assert is_projection_current(_projection(revision=5, fingerprint="fp-old", depends=True), current) is False
    assert (
        is_projection_current(
            _projection(revision=5, fingerprint="fp-new", depends=False, status=ProjectionStatus.FAILED),
            current,
        )
        is False
    )
    assert is_projection_current(
        _projection(revision=5, fingerprint="fp-new", depends=False),
        ProjectionStamp(5, "fp-new", LINEAGE_SCHEMA_VERSION + 1),
    ) is False
