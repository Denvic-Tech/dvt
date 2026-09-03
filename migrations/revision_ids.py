from __future__ import annotations

from collections.abc import Iterable
import re


REVISION_ID_PATTERN = re.compile(r"^\d{4}$")


def next_sequential_revision_id(revision_ids: Iterable[str]) -> str:
    """Return one more than the largest existing numeric Alembic revision ID."""
    revision_ids = list(revision_ids)
    invalid_revision_ids = [
        revision_id
        for revision_id in revision_ids
        if not REVISION_ID_PATTERN.fullmatch(revision_id)
    ]
    if invalid_revision_ids:
        raise ValueError(
            "Alembic revision IDs must contain exactly four digits: "
            f"{sorted(invalid_revision_ids)}"
        )

    numeric_revision_ids = [int(revision_id) for revision_id in revision_ids]
    next_revision_id = max(numeric_revision_ids, default=0) + 1
    if next_revision_id > 9999:
        raise ValueError("Alembic four-digit revision ID space is exhausted")
    return f"{next_revision_id:04d}"
