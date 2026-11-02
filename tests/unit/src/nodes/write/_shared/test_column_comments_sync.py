from __future__ import annotations

from sqlalchemy import create_engine

from src.nodes.write._shared import column_comments_sync
from src.nodes.write._shared.column_comments_sync import (
    plan_comment_actions,
    sync_table_column_comments,
)

CURRENT = [
    {"name": "client_id", "comment": None},
    {"name": "Amount", "comment": "Сумма"},
    {"name": "note", "comment": "Старый текст"},
    {"name": "dup", "comment": None},
    {"name": "DUP", "comment": None},
]


def test_plan_updates_only_differences_and_never_clears_existing_comments():
    actions = plan_comment_actions(
        CURRENT,
        {
            "client_id": "Идентификатор клиента",
            "amount": "Сумма",
            "note": "Новый текст",
            "missing": "Нет такой колонки",
            "Dup": "Неоднозначное имя: два кандидата без точного совпадения",
            "blank": "   ",
        },
    )

    assert [(action.type, action.column_name, action.comment) for action in actions] == [
        ("set_column_comment", "client_id", "Идентификатор клиента"),
        ("set_column_comment", "note", "Новый текст"),
    ]
    assert plan_comment_actions(CURRENT, {}) == []


def test_sync_skips_dialects_without_column_comments(monkeypatch):
    engine = create_engine("sqlite://")
    called = []
    monkeypatch.setattr(column_comments_sync, "apply_table_column_actions", lambda **kwargs: called.append(kwargs))

    updated = sync_table_column_comments(
        engine, table_name="events", schema_name=None, database_name=None, descriptions={"id": "x"}
    )

    assert updated == 0 and called == []
    assert sync_table_column_comments(engine, table_name="events", schema_name=None, database_name=None, descriptions={}) == 0
