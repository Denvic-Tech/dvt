from unittest.mock import AsyncMock

import pytest
from scripts.misc import backfill_data_catalog as backfill_module

from src.modules.data_catalog.domain import RebuildResult


class _Session:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


@pytest.mark.asyncio
async def test_backfill_counts_ok_skipped_and_failed_projects(monkeypatch):
    monkeypatch.setattr(
        backfill_module,
        "_list_projects",
        AsyncMock(return_value=[("p-ok", "org"), ("p-skip", "org"), ("p-fail", "org")]),
    )
    sessions: list[_Session] = []

    def session_factory():
        session = _Session()
        sessions.append(session)
        return session

    monkeypatch.setattr(backfill_module, "AsyncSessionLocal", session_factory)

    async def rebuild(*, session, project_id, organization_id, force, raise_on_error):
        assert force is True and raise_on_error is True
        if project_id == "p-fail":
            raise RuntimeError("boom")
        return RebuildResult(status="ok" if project_id == "p-ok" else "skipped")

    monkeypatch.setattr(backfill_module, "rebuild_project_catalog_projection", rebuild)

    summary = await backfill_module.backfill()

    assert (summary.total, summary.ok, summary.skipped, summary.failed) == (3, 1, 1, 1)
    assert summary.failures == [("p-fail", "boom")]
    assert sum(session.commit.await_count for session in sessions) == 2
    assert sum(session.rollback.await_count for session in sessions) == 1


@pytest.mark.asyncio
async def test_dry_run_does_not_touch_the_database(monkeypatch):
    monkeypatch.setattr(backfill_module, "_list_projects", AsyncMock(return_value=[("p1", "org")]))
    rebuild = AsyncMock()
    monkeypatch.setattr(backfill_module, "rebuild_project_catalog_projection", rebuild)

    summary = await backfill_module.backfill(dry_run=True)

    assert (summary.total, summary.skipped) == (1, 1)
    rebuild.assert_not_awaited()
