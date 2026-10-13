from unittest.mock import AsyncMock

import pytest
from scripts.misc import backfill_data_catalog as backfill_module

from src.modules.data_catalog.domain import ReconcileSummary


@pytest.mark.asyncio
async def test_backfill_forces_rebuild_by_default_and_passes_filters(monkeypatch):
    summary = ReconcileSummary(total=3, ok=1, skipped=1, failed=1, failures=[("p-fail", "boom")])
    reconcile = AsyncMock(return_value=summary)
    monkeypatch.setattr(backfill_module, "reconcile_catalog_projections", reconcile)

    result = await backfill_module.backfill(project_ids=["p1"], organization_id="org", batch_size=5)

    assert result is summary
    kwargs = reconcile.await_args.kwargs
    assert kwargs["session_factory"] is backfill_module.AsyncSessionLocal
    assert kwargs["force"] is True
    assert kwargs["dry_run"] is False
    assert kwargs["batch_size"] == 5
    assert kwargs["organization_id"] == "org"
    assert kwargs["project_ids"] == ["p1"]


@pytest.mark.asyncio
async def test_stale_only_and_dry_run_are_forwarded(monkeypatch):
    reconcile = AsyncMock(return_value=ReconcileSummary())
    monkeypatch.setattr(backfill_module, "reconcile_catalog_projections", reconcile)

    await backfill_module.backfill(stale_only=True, dry_run=True)

    kwargs = reconcile.await_args.kwargs
    assert kwargs["force"] is False
    assert kwargs["dry_run"] is True


def test_main_prints_failures_and_returns_nonzero_exit_code(monkeypatch, capsys):
    summary = ReconcileSummary(total=2, ok=1, failed=1, failures=[("p-fail", "boom")])

    async def fake_backfill(**kwargs):
        assert kwargs["stale_only"] is True
        assert kwargs["batch_size"] == 3
        return summary

    monkeypatch.setattr(backfill_module, "backfill", fake_backfill)

    code = backfill_module.main(["--stale-only", "--batch-size", "3"])

    out = capsys.readouterr().out
    assert code == 1
    assert "FAILED p-fail: boom" in out
    assert "total=2 ok=1 skipped=0 failed=1" in out
