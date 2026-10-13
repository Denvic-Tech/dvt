from __future__ import annotations

import pytest

from src.modules.data_catalog.domain import LINEAGE_SCHEMA_VERSION, ProjectRef, RebuildResult
from src.modules.data_catalog.flow import ReconcileCatalogProjections


class FakeProjectSource:
    def __init__(self, project_ids: list[str]) -> None:
        self.projects = [ProjectRef(project_id=pid, organization_id="org") for pid in sorted(project_ids)]
        self.calls: list[dict] = []

    async def list_projects(
        self,
        *,
        lineage_schema_version,
        stale_only,
        after_project_id,
        limit,
        organization_id=None,
        project_ids=None,
    ):
        self.calls.append(
            {
                "version": lineage_schema_version,
                "stale_only": stale_only,
                "after": after_project_id,
                "limit": limit,
                "organization_id": organization_id,
                "project_ids": project_ids,
            }
        )
        rows = [p for p in self.projects if after_project_id is None or p.project_id > after_project_id]
        if project_ids is not None:
            rows = [p for p in rows if p.project_id in project_ids]
        return rows[:limit]


async def _no_yield() -> None:
    return None


@pytest.mark.asyncio
async def test_counts_statuses_and_continues_after_runner_exception():
    source = FakeProjectSource(["p-ok", "p-skip", "p-fail", "p-boom"])
    seen: list[tuple[str, bool]] = []

    async def rebuild_one(project: ProjectRef, force: bool) -> RebuildResult:
        seen.append((project.project_id, force))
        if project.project_id == "p-boom":
            raise RuntimeError("database down")
        if project.project_id == "p-fail":
            return RebuildResult(status="failed", error="bad graph")
        return RebuildResult(status="ok" if project.project_id == "p-ok" else "skipped")

    use_case = ReconcileCatalogProjections(
        projects=source, rebuild_one=rebuild_one, batch_size=10, yield_control=_no_yield
    )
    summary = await use_case.execute()

    assert (summary.total, summary.ok, summary.skipped, summary.failed) == (4, 1, 1, 2)
    assert summary.failures == [("p-boom", "database down"), ("p-fail", "bad graph")]
    assert [force for _, force in seen] == [False] * 4
    assert source.calls[0]["version"] == LINEAGE_SCHEMA_VERSION
    assert source.calls[0]["stale_only"] is True


@pytest.mark.asyncio
async def test_pages_with_keyset_until_short_page():
    source = FakeProjectSource([f"p{i}" for i in range(5)])

    async def rebuild_one(project: ProjectRef, force: bool) -> RebuildResult:
        return RebuildResult(status="ok")

    use_case = ReconcileCatalogProjections(
        projects=source, rebuild_one=rebuild_one, batch_size=2, yield_control=_no_yield
    )
    summary = await use_case.execute()

    assert summary.total == summary.ok == 5
    assert [call["after"] for call in source.calls] == [None, "p1", "p3"]
    assert all(call["limit"] == 2 for call in source.calls)


@pytest.mark.asyncio
async def test_exact_page_boundary_issues_one_extra_empty_query():
    source = FakeProjectSource(["p0", "p1"])

    async def rebuild_one(project: ProjectRef, force: bool) -> RebuildResult:
        return RebuildResult(status="ok")

    use_case = ReconcileCatalogProjections(
        projects=source, rebuild_one=rebuild_one, batch_size=2, yield_control=_no_yield
    )
    summary = await use_case.execute()

    assert summary.total == 2
    assert [call["after"] for call in source.calls] == [None, "p1"]


@pytest.mark.asyncio
async def test_dry_run_counts_without_rebuilding_and_force_switches_to_all_projects():
    source = FakeProjectSource(["p0", "p1"])
    calls: list[ProjectRef] = []

    async def rebuild_one(project: ProjectRef, force: bool) -> RebuildResult:
        calls.append(project)
        return RebuildResult(status="ok")

    use_case = ReconcileCatalogProjections(
        projects=source, rebuild_one=rebuild_one, batch_size=10, yield_control=_no_yield
    )
    summary = await use_case.execute(force=True, dry_run=True, organization_id="org", project_ids=["p1"])

    assert (summary.total, summary.skipped) == (1, 1)
    assert calls == []
    assert source.calls[0]["stale_only"] is False
    assert source.calls[0]["organization_id"] == "org"
    assert source.calls[0]["project_ids"] == ["p1"]


@pytest.mark.asyncio
async def test_force_is_passed_to_runner():
    source = FakeProjectSource(["p0"])
    forces: list[bool] = []

    async def rebuild_one(project: ProjectRef, force: bool) -> RebuildResult:
        forces.append(force)
        return RebuildResult(status="ok")

    use_case = ReconcileCatalogProjections(
        projects=source, rebuild_one=rebuild_one, batch_size=10, yield_control=_no_yield
    )
    await use_case.execute(force=True)

    assert forces == [True]


def test_rejects_non_positive_batch_size():
    async def rebuild_one(project: ProjectRef, force: bool) -> RebuildResult:
        return RebuildResult(status="ok")

    with pytest.raises(ValueError):
        ReconcileCatalogProjections(projects=FakeProjectSource([]), rebuild_one=rebuild_one, batch_size=0)
