from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.gateway.deps.project import get_user_project_by_path
from services.gateway.routes.data_catalog import lineage as lineage_module
from services.gateway.routes.data_catalog.lineage import router

from src.db.session import get_async_session
from src.modules.data_catalog.domain import (
    ExplainDirection,
    ExplainStep,
    FieldExplanation,
    LineageNodePortNotFoundError,
    LineageOp,
    LineageProvenance,
    LineageRef,
    NodeFieldsResult,
    NodeFieldView,
    PortStatus,
    ResolvedDescription,
)

SOURCE = LineageRef.dataset_field("d1", "f1")
COLUMN = LineageRef.node_column("n1", "output", "customer_id")


def _fields_result() -> NodeFieldsResult:
    view = NodeFieldView(
        name="customer_id", ref=COLUMN, op=LineageOp.RENAME, origin=SOURCE, deps=(LineageRef.node_column("r", "output", "id"),),
        deps_unknown=False, description="Customer id", provenance=LineageProvenance.INHERITED, description_source=SOURCE,
        explanation="Переименовано из id",
    )
    return NodeFieldsResult(project_id="p1", node_id="n1", node_name="DataFrameRenameColumns", port="output", role="output", status=PortStatus.RESOLVED, fields=(view,), available_ports=("output",))


def _explanation() -> FieldExplanation:
    return FieldExplanation(
        root=COLUMN,
        direction=ExplainDirection.UPSTREAM,
        steps=(ExplainStep(ref=COLUMN, depth=0, op=LineageOp.RENAME, text="Renamed from id", node_id="n1", node_name="DataFrameRenameColumns", port="output", column="customer_id"),),
        description=ResolvedDescription(text="Customer id", provenance=LineageProvenance.INHERITED, source=SOURCE),
    )


@pytest.fixture
def harness(monkeypatch):
    session = SimpleNamespace(commit=AsyncMock())
    use_cases = SimpleNamespace(
        get_node_fields=SimpleNamespace(execute=AsyncMock(return_value=_fields_result())),
        explain_field=SimpleNamespace(execute=AsyncMock(return_value=_explanation())),
    )
    monkeypatch.setattr(lineage_module, "get_data_catalog_use_cases", lambda session, redis=None: use_cases)

    app = FastAPI()
    app.include_router(router)

    async def session_override():
        yield session

    app.dependency_overrides[get_async_session] = session_override
    app.dependency_overrides[get_user_project_by_path] = lambda: SimpleNamespace(id="p1", organization_id="org")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return SimpleNamespace(client=client, session=session, use_cases=use_cases)


@pytest.mark.asyncio
async def test_node_fields_route_passes_locale_and_renders_refs(harness):
    async with harness.client as client:
        response = await client.get("/projects/p1/lineage/nodes/n1/fields?port=output", headers={"X-Language": "ru"})

    assert response.status_code == 200, response.text
    kwargs = harness.use_cases.get_node_fields.execute.await_args.kwargs
    assert (kwargs["project_id"], kwargs["organization_id"], kwargs["node_id"], kwargs["port"], kwargs["locale"]) == ("p1", "org", "n1", "output", "ru")
    body = response.json()
    field = body["fields"][0]
    assert field["origin"] == {"key": "ds:d1:f1", "kind": "ds", "dataset_id": "d1", "field_id": "f1", "node_id": None, "port": None, "column": None}
    assert field["description_provenance"] == "inherited" and field["explanation"] == "Переименовано из id"
    harness.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_explain_route_validates_arguments_and_maps_not_found(harness):
    async with harness.client as client:
        ok = await client.get("/projects/p1/lineage/explain?node_id=n1&column=customer_id&direction=upstream&max_depth=5")
        assert ok.status_code == 200, ok.text
        kwargs = harness.use_cases.explain_field.execute.await_args.kwargs
        assert kwargs["direction"] is ExplainDirection.UPSTREAM and kwargs["max_depth"] == 5 and kwargs["locale"] == "en"
        assert ok.json()["description"] == "Customer id" and ok.json()["steps"][0]["text"] == "Renamed from id"

        bad = await client.get("/projects/p1/lineage/explain?node_id=n1&column=c&direction=sideways")
        assert bad.status_code == 422

        harness.use_cases.explain_field.execute.side_effect = LineageNodePortNotFoundError("no lineage")
        missing = await client.get("/projects/p1/lineage/explain?node_id=n1&column=c")
        assert missing.status_code == 404
