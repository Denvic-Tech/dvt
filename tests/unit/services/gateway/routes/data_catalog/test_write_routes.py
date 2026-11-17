from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.gateway.deps.redis import get_redis_bytes
from services.gateway.routes.data_catalog import impl as impl_module
from services.gateway.routes.data_catalog.impl import router

from src.db.session import get_async_session
from src.modules.data_catalog.domain import (
    UNSET,
    Dataset,
    DatasetDetails,
    DatasetField,
    DatasetFieldNotFoundError,
    DatasetNotFoundError,
    FieldRenameNotApplicableError,
    FieldStatus,
    Freshness,
    RefreshOutcome,
    db_table_locator,
)
from src.modules.user.infra.fastapi.dependencies import get_user_access_only

NOW = datetime(2026, 10, 7, tzinfo=UTC)


def _details() -> DatasetDetails:
    dataset = Dataset(
        id="d1",
        organization_id="org",
        locator=db_table_locator("postgresql", "db", 5432, "main", "public", "t"),
        physical_key="postgresql://db:5432/main/public/t",
        created_at=NOW,
        updated_at=NOW,
    )
    field = DatasetField(
        id="f1",
        dataset_id="d1",
        name="id",
        status=FieldStatus.OK,
        first_seen_at=NOW,
        last_seen_at=NOW,
        source_comment="from db",
    )
    return DatasetDetails(dataset=dataset, freshness=Freshness.UNVERIFIED, fields=(field,))


@pytest.fixture
def harness(monkeypatch):
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    use_cases = SimpleNamespace(
        set_descriptions=SimpleNamespace(execute=AsyncMock()),
        confirm_rename=SimpleNamespace(execute=AsyncMock()),
        refresh_schema=SimpleNamespace(execute=AsyncMock(return_value=RefreshOutcome(status="failed", error="down"))),
        get_dataset=SimpleNamespace(execute=AsyncMock(return_value=_details())),
    )
    monkeypatch.setattr(impl_module, "get_data_catalog_use_cases", lambda session, redis=None: use_cases)
    monkeypatch.setattr(impl_module, "build_viewer", lambda user: SimpleNamespace(user_id=user.id))
    monkeypatch.setattr(impl_module, "build_schema_actor", lambda user: SimpleNamespace(id=user.id))

    app = FastAPI()
    app.include_router(router)

    async def session_override():
        yield session

    async def redis_override():
        yield object()

    app.dependency_overrides[get_async_session] = session_override
    app.dependency_overrides[get_redis_bytes] = redis_override
    app.dependency_overrides[get_user_access_only] = lambda: SimpleNamespace(
        id="u1", organization_id="org", role="user"
    )
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return SimpleNamespace(client=client, session=session, use_cases=use_cases)


@pytest.mark.asyncio
async def test_patch_distinguishes_omitted_and_null_description(harness):
    async with harness.client as client:
        response = await client.patch("/data-catalog/datasets/d1", json={"fields": [{"name": "id", "description": None}]})
        assert response.status_code == 200, response.text
        kwargs = harness.use_cases.set_descriptions.execute.await_args.kwargs
        assert kwargs["description"] is UNSET
        assert kwargs["fields"][0].description is None and kwargs["fields"][0].name == "id"
        assert kwargs["actor_user_id"] == "u1"

        response = await client.patch("/data-catalog/datasets/d1", json={"description": None})
        assert response.status_code == 200
        assert harness.use_cases.set_descriptions.execute.await_args.kwargs["description"] is None

    body = response.json()
    assert body["fields"][0]["effective_description"] == "from db"
    assert body["fields"][0]["description_provenance"] == "source"
    assert body["description_provenance"] == "none"
    assert harness.session.commit.await_count == 2


@pytest.mark.asyncio
async def test_patch_validation_and_domain_errors(harness):
    async with harness.client as client:
        missing_key = await client.patch("/data-catalog/datasets/d1", json={"fields": [{"name": "id"}]})
        assert missing_key.status_code == 422, "ключ description обязателен"

        both_refs = await client.patch(
            "/data-catalog/datasets/d1", json={"fields": [{"name": "id", "field_id": "f1", "description": "x"}]}
        )
        assert both_refs.status_code == 422

        harness.use_cases.set_descriptions.execute.side_effect = DatasetFieldNotFoundError("ghost")
        unknown = await client.patch("/data-catalog/datasets/d1", json={"fields": [{"name": "ghost", "description": "x"}]})
        assert unknown.status_code == 422

        harness.use_cases.set_descriptions.execute.side_effect = DatasetNotFoundError("d1")
        hidden = await client.patch("/data-catalog/datasets/d1", json={"description": "x"})
        assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_refresh_returns_failed_status_with_200_and_commits(harness):
    async with harness.client as client:
        response = await client.post("/data-catalog/datasets/d1/refresh")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"] == "down"
    harness.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_rename_confirm_maps_precondition_failure_to_422(harness):
    harness.use_cases.confirm_rename.execute.side_effect = FieldRenameNotApplicableError("not missing")
    async with harness.client as client:
        response = await client.post(
            "/data-catalog/datasets/d1/fields/rename-confirm",
            json={"missing": {"name": "a"}, "new": {"field_id": "f2"}},
        )
    assert response.status_code == 422
    assert "not missing" in response.json()["detail"]
    harness.session.commit.assert_not_awaited()
