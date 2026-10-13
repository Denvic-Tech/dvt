from __future__ import annotations

import pytest

from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.data_catalog.domain import LINEAGE_SCHEMA_VERSION
from src.modules.data_catalog.infra import SQLAlchemyCatalogProjectSource
from src.modules.data_catalog.infra.db_models import ProjectCatalogProjectionRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord


async def _seed(session) -> tuple[str, str]:
    org_a = OrganizationRecord(name="A")
    org_b = OrganizationRecord(name="B")
    session.add_all([org_a, org_b])
    await session.flush()
    user = UserRecord(
        email="owner@example.com",
        hashed_password="h",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.USER.value,
        organization_id=org_a.id,
    )
    session.add(user)
    await session.flush()

    def project(pid: str, org_id: str, *, graph_revision: int = 3, is_deleted: bool = False) -> ProjectRecord:
        return ProjectRecord(
            id=pid,
            name=pid,
            user_id=user.id,
            organization_id=org_id,
            graph_revision=graph_revision,
            is_deleted=is_deleted,
        )

    def projection(pid: str, org_id: str, *, graph_revision: int = 3, version: int = LINEAGE_SCHEMA_VERSION):
        return ProjectCatalogProjectionRecord(
            project_id=pid,
            organization_id=org_id,
            graph_revision=graph_revision,
            variables_fingerprint="fp",
            lineage_schema_version=version,
            status="ok",
        )

    session.add_all(
        [
            project("p1-missing", org_a.id),
            project("p2-old-version", org_a.id),
            project("p3-revision-mismatch", org_a.id),
            project("p4-current", org_a.id),
            project("p5-deleted", org_a.id, is_deleted=True),
            project("p6-other-org", org_b.id),
        ]
    )
    await session.flush()
    session.add_all(
        [
            projection("p2-old-version", org_a.id, version=LINEAGE_SCHEMA_VERSION - 1),
            projection("p3-revision-mismatch", org_a.id, graph_revision=2),
            projection("p4-current", org_a.id),
        ]
    )
    await session.flush()
    return org_a.id, org_b.id


def _ids(rows) -> list[str]:
    return [row.project_id for row in rows]


@pytest.mark.asyncio
async def test_stale_only_selects_missing_outdated_and_mismatched_projections(async_test_db_session):
    await _seed(async_test_db_session)
    source = SQLAlchemyCatalogProjectSource(async_test_db_session)

    rows = await source.list_projects(
        lineage_schema_version=LINEAGE_SCHEMA_VERSION,
        stale_only=True,
        after_project_id=None,
        limit=100,
    )

    assert _ids(rows) == ["p1-missing", "p2-old-version", "p3-revision-mismatch", "p6-other-org"]
    assert rows[0].organization_id


@pytest.mark.asyncio
async def test_all_projects_mode_keeps_current_but_never_deleted(async_test_db_session):
    await _seed(async_test_db_session)
    source = SQLAlchemyCatalogProjectSource(async_test_db_session)

    rows = await source.list_projects(
        lineage_schema_version=LINEAGE_SCHEMA_VERSION,
        stale_only=False,
        after_project_id=None,
        limit=100,
    )

    assert "p4-current" in _ids(rows)
    assert "p5-deleted" not in _ids(rows)


@pytest.mark.asyncio
async def test_keyset_pagination_and_limit(async_test_db_session):
    await _seed(async_test_db_session)
    source = SQLAlchemyCatalogProjectSource(async_test_db_session)

    first = await source.list_projects(
        lineage_schema_version=LINEAGE_SCHEMA_VERSION, stale_only=True, after_project_id=None, limit=2
    )
    second = await source.list_projects(
        lineage_schema_version=LINEAGE_SCHEMA_VERSION,
        stale_only=True,
        after_project_id=first[-1].project_id,
        limit=2,
    )

    assert _ids(first) == ["p1-missing", "p2-old-version"]
    assert _ids(second) == ["p3-revision-mismatch", "p6-other-org"]


@pytest.mark.asyncio
async def test_filters_by_organization_and_project_ids(async_test_db_session):
    _, org_b = await _seed(async_test_db_session)
    source = SQLAlchemyCatalogProjectSource(async_test_db_session)

    by_org = await source.list_projects(
        lineage_schema_version=LINEAGE_SCHEMA_VERSION,
        stale_only=True,
        after_project_id=None,
        limit=100,
        organization_id=org_b,
    )
    by_ids = await source.list_projects(
        lineage_schema_version=LINEAGE_SCHEMA_VERSION,
        stale_only=False,
        after_project_id=None,
        limit=100,
        project_ids=["p4-current", "p5-deleted"],
    )
    empty = await source.list_projects(
        lineage_schema_version=LINEAGE_SCHEMA_VERSION,
        stale_only=False,
        after_project_id=None,
        limit=100,
        project_ids=[],
    )

    assert _ids(by_org) == ["p6-other-org"]
    assert _ids(by_ids) == ["p4-current"]
    assert empty == []
