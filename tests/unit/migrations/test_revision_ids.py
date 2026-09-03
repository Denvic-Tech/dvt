import pytest

from migrations.revision_ids import next_sequential_revision_id


def test_next_sequential_revision_id_uses_largest_numeric_revision() -> None:
    assert next_sequential_revision_id(["0001", "0003"]) == "0004"


def test_next_sequential_revision_id_rejects_non_four_digit_revisions() -> None:
    with pytest.raises(ValueError, match="exactly four digits"):
        next_sequential_revision_id(["0001", "feature_head", "0010"])


def test_next_sequential_revision_id_starts_at_one() -> None:
    assert next_sequential_revision_id([]) == "0001"


def test_next_sequential_revision_id_rejects_overflow() -> None:
    with pytest.raises(ValueError, match="space is exhausted"):
        next_sequential_revision_id(["9999"])
