from __future__ import annotations

from collections.abc import Iterable, Sequence

from ..catalog_values import RawLocator, SqlTableRef
from .physical_key import supports_schemas


def select_table_candidates(
    refs: Sequence[SqlTableRef],
    *,
    cte_names: Iterable[str] = (),
    excluded_names: Iterable[str] = (),
) -> list[SqlTableRef]:
    """Убирает CTE-алиасы и временные таблицы (имена DataFrame-входов), дедуплицирует."""
    skip = {name.lower() for name in cte_names} | {name.lower() for name in excluded_names}
    seen: set[tuple[str | None, str | None, str]] = set()
    result: list[SqlTableRef] = []
    for ref in refs:
        if not ref.table:
            continue
        if ref.schema is None and ref.catalog is None and ref.table.lower() in skip:
            continue
        key = (
            ref.catalog.lower() if ref.catalog else None,
            ref.schema.lower() if ref.schema else None,
            ref.table.lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(ref)
    return result


def sql_table_ref_to_raw_locator(ref: SqlTableRef, *, dialect: str) -> RawLocator:
    """sqlglot даёт catalog.db.name; для диалектов без схем db означает базу данных."""
    if supports_schemas(dialect):
        return RawLocator(table=ref.table, schema=ref.schema, database=ref.catalog)
    return RawLocator(table=ref.table, schema=None, database=ref.schema or ref.catalog)
