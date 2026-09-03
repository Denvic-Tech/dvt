"""normalize task source values

Revision ID: 0041
Revises: 0040
Create Date: 2026-03-25 12:30:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0041"
down_revision: Union[str, Sequence[str], None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TASK_SOURCE_CONSTRAINT_NAME = "task_source"
TASK_SOURCE_VALUES = ("UI", "API", "SCHEDULER")


def _normalize_task_source(value: str | None, *, uppercase: bool) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return value

    normalized = normalized.upper()
    if normalized not in TASK_SOURCE_VALUES:
        return value

    return normalized if uppercase else normalized.lower()


def _build_task_source_updates(
    rows: Sequence[dict[str, str | None]],
    *,
    uppercase: bool,
) -> list[dict[str, str]]:
    updates: list[dict[str, str]] = []
    for row in rows:
        source = row["source"]
        normalized = _normalize_task_source(source, uppercase=uppercase)
        if source is None or normalized is None or normalized == source:
            continue

        updates.append({"task_id": str(row["task_id"]), "source": normalized})

    return updates


def _collect_unexpected_task_sources(rows: Sequence[dict[str, str | None]]) -> list[str]:
    unexpected = {
        str(source)
        for row in rows
        if (source := row["source"]) is not None
        and _normalize_task_source(source, uppercase=True) == source
        and source not in TASK_SOURCE_VALUES
    }
    return sorted(unexpected)


def _apply_updates(bind, updates: Sequence[dict[str, str]]) -> None:
    if not updates:
        return

    bind.execute(
        sa.text("UPDATE tasks SET source = :source WHERE task_id = :task_id"),
        list(updates),
    )


def _fetch_task_sources(bind) -> list[dict[str, str | None]]:
    return list(
        bind.execute(sa.text("SELECT task_id, source FROM tasks"))
        .mappings()
        .all()
    )


def _validate_task_sources(rows: Sequence[dict[str, str | None]]) -> None:
    unexpected = _collect_unexpected_task_sources(rows)
    if unexpected:
        raise RuntimeError(
            "tasks.source contains unsupported values: "
            + ", ".join(sorted(unexpected))
        )


def upgrade() -> None:
    bind = op.get_bind()

    rows = _fetch_task_sources(bind)
    _validate_task_sources(rows)
    _apply_updates(bind, _build_task_source_updates(rows, uppercase=True))

    op.create_check_constraint(
        TASK_SOURCE_CONSTRAINT_NAME,
        "tasks",
        "source IN ('UI', 'API', 'SCHEDULER')",
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_constraint(TASK_SOURCE_CONSTRAINT_NAME, "tasks", type_="check")

    rows = _fetch_task_sources(bind)
    _validate_task_sources(rows)
    _apply_updates(bind, _build_task_source_updates(rows, uppercase=False))
