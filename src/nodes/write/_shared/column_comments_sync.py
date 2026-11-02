"""Синхронизация комментариев колонок таблицы с описаниями каталога.

Правило: каталог побеждает там, где у него есть текст; пустое описание никогда не стирает
существующий комментарий. Обновляются только расхождения, одной транзакцией, через тот же DDL,
что и ручные действия над колонками в Gateway.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import sqlalchemy as sa

from core.db.ddl.column_actions import apply_table_column_actions
from core.db.ddl.column_comments import column_comments_supported
from core.db.ddl.models import TableColumnAction
from core.metadata.db_metadata.comments import normalize_comment


def plan_comment_actions(
    current_columns: Sequence[Mapping[str, object]],
    descriptions: Mapping[str, str],
) -> list[TableColumnAction]:
    """Действия `set_column_comment` для целевых колонок, чей комментарий отличается от описания.

    `current_columns`: строки инспектора (`name`, `comment`). Имена сопоставляются точно, затем
    без учёта регистра, если совпадение единственное. Неизвестные колонки пропускаются.
    """
    by_name = {str(column["name"]): column for column in current_columns}
    lowered: dict[str, list[str]] = {}
    for name in by_name:
        lowered.setdefault(name.lower(), []).append(name)

    actions: list[TableColumnAction] = []
    for target, text in descriptions.items():
        desired = normalize_comment(text)
        if desired is None:
            continue
        resolved = target if target in by_name else None
        if resolved is None:
            candidates = lowered.get(target.lower(), [])
            resolved = candidates[0] if len(candidates) == 1 else None
        if resolved is None:
            continue
        if normalize_comment(by_name[resolved].get("comment")) == desired:
            continue
        actions.append(TableColumnAction(type="set_column_comment", column_name=resolved, comment=desired))
    return actions


def sync_table_column_comments(
    engine: sa.Engine,
    *,
    table_name: str,
    schema_name: str | None,
    database_name: str | None,
    descriptions: Mapping[str, str],
) -> int:
    """Блокирующая: читает текущие комментарии, применяет расхождения, возвращает их число."""
    if not descriptions or not column_comments_supported(engine.dialect):
        return 0
    inspector = sa.inspect(engine)
    current = inspector.get_columns(table_name, schema=schema_name)
    actions = plan_comment_actions(current, descriptions)
    if not actions:
        return 0
    apply_table_column_actions(
        engine=engine,
        table_name=table_name,
        actions=actions,
        schema_name=schema_name,
        database_name=database_name,
    )
    return len(actions)
