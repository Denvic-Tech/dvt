from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.gateway.routes.internal.ai_mcp import catalog
from services.gateway.routes.internal.ai_mcp.errors import AIMCPHTTPError

from src.modules.ai_mcp_access.domain import MCPAccessScope, ResourceScope, ResourceScopeMode
from src.modules.data_catalog.domain import (
    Dataset,
    DatasetConnection,
    DatasetSearchHit,
    DatasetSearchPage,
    DatasetUsageEntry,
    LinkDirection,
    LinkKind,
    PhysicalLocator,
    ResolvedVia,
)

NOW = datetime(2026, 10, 7, tzinfo=UTC)


def _principal(*, projects=("p-allowed",), connections=()):
    scope = MCPAccessScope(
        projects=ResourceScope(ResourceScopeMode.SELECTED, frozenset(projects)),
        db_connections=ResourceScope(ResourceScopeMode.SELECTED, frozenset(connections)),
    )
    user = SimpleNamespace(id="u1", organization_id="org", role="user")
    return SimpleNamespace(
        user=user,
        token=SimpleNamespace(id="t1", access_scope=scope),
        allows_project=scope.allows_project,
        allows_connection=scope.allows_connection,
    )


def _dataset(dataset_id: str) -> Dataset:
    return Dataset(
        id=dataset_id,
        organization_id="org",
        locator=PhysicalLocator("postgresql", "db", 5432, "main", "public", dataset_id),
        physical_key=f"postgresql://db:5432/main/public/{dataset_id}",
        created_at=NOW,
        updated_at=NOW,
    )


def _usage(project_id: str) -> DatasetUsageEntry:
    return DatasetUsageEntry(
        project_id=project_id,
        project_name=project_id,
        node_id="n",
        node_name="ReadTableFromDBV3",
        direction=LinkDirection.READ,
        kind=LinkKind.DECLARED,
        resolved_via=ResolvedVia.CONST,
        graph_revision=1,
        updated_at=NOW,
    )


class _Links:
    def __init__(self, mapping):
        self._mapping = mapping

    async def list_project_ids(self, dataset_id, viewer):
        return self._mapping.get(dataset_id, [])


class _Connections:
    def __init__(self, mapping):
        self._mapping = mapping

    async def list_for_dataset(self, dataset_id):
        return [
            DatasetConnection(dataset_id, connection_id, "r", NOW, NOW)
            for connection_id in self._mapping.get(dataset_id, [])
        ]


@pytest.fixture
def wire(monkeypatch):
    def _wire(*, links=None, connections=None, use_cases=None):
        monkeypatch.setattr(catalog, "SQLAlchemyDatasetLinkRepository", lambda session: _Links(links or {}))
        monkeypatch.setattr(
            catalog, "SQLAlchemyDatasetConnectionRepository", lambda session: _Connections(connections or {})
        )
        monkeypatch.setattr(catalog, "get_data_catalog_use_cases", lambda session, redis=None: use_cases)
        monkeypatch.setattr(catalog, "build_viewer", lambda user: SimpleNamespace(user_id=user.id))
        monkeypatch.setattr(catalog, "build_schema_actor", lambda user: SimpleNamespace(id=user.id))

    return _wire


@pytest.mark.asyncio
async def test_search_hides_datasets_outside_token_scope(wire):
    page = DatasetSearchPage(
        items=tuple(
            DatasetSearchHit(_dataset(name), 0, 1, 0) for name in ("visible_project", "visible_connection", "hidden")
        )
    )
    wire(
        links={"visible_project": ["p-allowed"], "hidden": ["p-other"]},
        connections={"visible_connection": ["conn-allowed"]},
        use_cases=SimpleNamespace(search=SimpleNamespace(execute=AsyncMock(return_value=page))),
    )

    result = await catalog.search_datasets(
        principal=_principal(connections=("conn-allowed",)), session=object()
    )

    assert [item["id"] for item in result["items"]] == ["visible_project", "visible_connection"]
    assert result["items"][0]["locator"]["schema"] == "public"


@pytest.mark.asyncio
async def test_search_rejects_filters_outside_scope_and_bad_limit(wire):
    wire(use_cases=SimpleNamespace())
    with pytest.raises(AIMCPHTTPError) as denied_project:
        await catalog.search_datasets(principal=_principal(), session=object(), project_id="p-other")
    assert denied_project.value.detail["code"] == "PROJECT_NOT_FOUND_OR_DENIED"

    with pytest.raises(AIMCPHTTPError) as bad_limit:
        await catalog.search_datasets(principal=_principal(), session=object(), limit=0)
    assert bad_limit.value.detail["code"] == "INVALID_ARGUMENTS"


@pytest.mark.asyncio
async def test_usage_is_filtered_by_token_projects_and_hidden_dataset_is_denied(wire):
    get_usage = SimpleNamespace(execute=AsyncMock(return_value=[_usage("p-allowed"), _usage("p-other")]))
    wire(links={"d1": ["p-allowed", "p-other"]}, use_cases=SimpleNamespace(get_usage=get_usage))

    result = await catalog.get_dataset_usage(principal=_principal(), session=object(), dataset_id="d1")
    assert [item["project_id"] for item in result["items"]] == ["p-allowed"]

    with pytest.raises(AIMCPHTTPError) as denied:
        await catalog.get_dataset_usage(principal=_principal(), session=object(), dataset_id="unknown")
    assert denied.value.detail["code"] == "DATASET_NOT_FOUND_OR_DENIED"


@pytest.mark.asyncio
async def test_all_scope_token_skips_per_dataset_checks(wire):
    scope = MCPAccessScope(
        projects=ResourceScope(ResourceScopeMode.ALL),
        db_connections=ResourceScope(ResourceScopeMode.SELECTED, frozenset()),
    )
    principal = SimpleNamespace(
        user=SimpleNamespace(id="u1", organization_id="org", role="user"),
        token=SimpleNamespace(id="t", access_scope=scope),
        allows_project=scope.allows_project,
        allows_connection=scope.allows_connection,
    )
    get_usage = SimpleNamespace(execute=AsyncMock(return_value=[_usage("any")]))
    wire(use_cases=SimpleNamespace(get_usage=get_usage))

    result = await catalog.get_dataset_usage(principal=principal, session=object(), dataset_id="d1")
    assert [item["project_id"] for item in result["items"]] == ["any"]


def _details_fixture():
    from src.modules.data_catalog.domain import DatasetDetails, Freshness

    return DatasetDetails(dataset=_dataset("d1"), freshness=Freshness.UNVERIFIED)


@pytest.mark.asyncio
async def test_set_dataset_description_distinguishes_omitted_clear_and_text(wire):
    from src.modules.data_catalog.domain import UNSET

    set_descriptions = SimpleNamespace(execute=AsyncMock())
    get_dataset = SimpleNamespace(execute=AsyncMock(return_value=_details_fixture()))
    wire(links={"d1": ["p-allowed"]}, use_cases=SimpleNamespace(set_descriptions=set_descriptions, get_dataset=get_dataset))

    await catalog.set_dataset_description(
        principal=_principal(), session=object(), dataset_id="d1", fields=[{"name": "id", "description": None}]
    )
    kwargs = set_descriptions.execute.await_args.kwargs
    assert kwargs["description"] is UNSET
    assert kwargs["fields"][0].description is None
    assert kwargs["actor_user_id"] == "u1"

    await catalog.set_dataset_description(
        principal=_principal(), session=object(), dataset_id="d1", clear_description=True
    )
    assert set_descriptions.execute.await_args.kwargs["description"] is None

    result = await catalog.set_dataset_description(
        principal=_principal(), session=object(), dataset_id="d1", description="text"
    )
    assert set_descriptions.execute.await_args.kwargs["description"] == "text"
    assert result["description_provenance"] == "none"


@pytest.mark.asyncio
async def test_set_dataset_description_rejects_bad_arguments_and_hidden_dataset(wire):
    wire(links={"d1": ["p-allowed"]}, use_cases=SimpleNamespace())

    with pytest.raises(AIMCPHTTPError) as extra:
        await catalog.set_dataset_description(principal=_principal(), session=object(), dataset_id="d1", bogus=1)
    assert extra.value.detail["code"] == "INVALID_ARGUMENTS"

    with pytest.raises(AIMCPHTTPError) as conflict:
        await catalog.set_dataset_description(
            principal=_principal(), session=object(), dataset_id="d1", description="x", clear_description=True
        )
    assert conflict.value.detail["code"] == "INVALID_ARGUMENTS"

    with pytest.raises(AIMCPHTTPError) as hidden:
        await catalog.set_dataset_description(principal=_principal(), session=object(), dataset_id="hidden", description="x")
    assert hidden.value.detail["code"] == "DATASET_NOT_FOUND_OR_DENIED"


@pytest.mark.asyncio
async def test_refresh_and_rename_handlers(wire):
    from src.modules.data_catalog.domain import FieldRenameNotApplicableError, RefreshOutcome

    refresh = SimpleNamespace(execute=AsyncMock(return_value=RefreshOutcome(status="synced", new=1, affected_project_ids=("p-allowed",))))
    confirm = SimpleNamespace(execute=AsyncMock(side_effect=FieldRenameNotApplicableError("old is not missing")))
    wire(
        links={"d1": ["p-allowed"]},
        use_cases=SimpleNamespace(refresh_schema=refresh, confirm_rename=confirm, get_dataset=SimpleNamespace(execute=AsyncMock())),
    )

    result = await catalog.refresh_dataset(principal=_principal(), session=object(), redis=object(), dataset_id="d1")
    assert result == {"status": "synced", "new": 1, "missing": 0, "type_changed": 0, "affected_project_ids": ["p-allowed"], "error": None, "error_kind": None}

    with pytest.raises(AIMCPHTTPError) as error:
        await catalog.confirm_field_rename(
            principal=_principal(), session=object(), dataset_id="d1", missing_field={"name": "a"}, new_field={"name": "b"}
        )
    assert error.value.detail["code"] == "INVALID_ARGUMENTS"
    assert "old is not missing" in error.value.detail["message"]
