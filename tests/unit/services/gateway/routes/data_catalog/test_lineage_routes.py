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
    ColumnDescriptionChange,
    ColumnGroup,
    ColumnOccurrence,
    ColumnRow,
    DescriptionTarget,
    ExplainDirection,
    ExplainStep,
    FieldExplanation,
    LineageNodePortNotFoundError,
    LineageOp,
    LineageProvenance,
    LineageRef,
    NodeColumnDescriptionsResult,
    NodeFieldsResult,
    NodeFieldView,
    PortStatus,
    ProjectColumnsResult,
    ResolvedDescription,
)
from src.modules.user.infra.fastapi.dependencies import get_user_access_only

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


def _project_columns() -> ProjectColumnsResult:
    declared = ResolvedDescription(text="Клиент", provenance=LineageProvenance.DECLARED, source=COLUMN)
    occurrence = ColumnOccurrence(
        ref=COLUMN, node_id="n1", node_name="DataFrameRenameColumns", port="output", role="output", column="customer_id",
        op=LineageOp.RENAME, deps=(LineageRef.node_column("r", "output", "id"),), deps_unknown=False, depth=2,
        description=declared, is_override=True, description_updated_by="u1",
    )
    group = ColumnGroup(
        origin=SOURCE, description=ResolvedDescription(text="Customer id", provenance=LineageProvenance.DECLARED, source=SOURCE),
        occurrences=(occurrence,), dataset_id="d1", dataset_location="main.public.customers @ db:5432", field_name="id",
    )
    row = ColumnRow(
        id=COLUMN.key, name="customer_id", origin=SOURCE, start=COLUMN, description=declared, occurrences=(occurrence,),
        targets=(DescriptionTarget(scope="project", node_id="n1", port="output", column="customer_id"),),
        dataset_id="d1", dataset_location="main.public.customers @ db:5432", field_name="id",
        is_rename=True, renamed_from="id",
    )
    return ProjectColumnsResult(project_id="p1", groups=(group,), rows=(row,))


@pytest.fixture
def harness(monkeypatch):
    session = SimpleNamespace(commit=AsyncMock())
    use_cases = SimpleNamespace(
        get_node_fields=SimpleNamespace(execute=AsyncMock(return_value=_fields_result())),
        explain_field=SimpleNamespace(execute=AsyncMock(return_value=_explanation())),
        set_node_column_descriptions=SimpleNamespace(
            execute=AsyncMock(return_value=NodeColumnDescriptionsResult(node_id="n1", port="df_out"))
        ),
        get_project_columns=SimpleNamespace(execute=AsyncMock(return_value=_project_columns())),
    )
    monkeypatch.setattr(lineage_module, "get_data_catalog_use_cases", lambda session, redis=None: use_cases)

    app = FastAPI()
    app.include_router(router)

    async def session_override():
        yield session

    app.dependency_overrides[get_async_session] = session_override
    app.dependency_overrides[get_user_project_by_path] = lambda: SimpleNamespace(id="p1", organization_id="org")
    app.dependency_overrides[get_user_access_only] = lambda: SimpleNamespace(id="u1", organization_id="org")
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
async def test_project_columns_route_renders_groups_and_overrides(harness):
    async with harness.client as client:
        response = await client.get("/projects/p1/lineage/columns")

    assert response.status_code == 200, response.text
    kwargs = harness.use_cases.get_project_columns.execute.await_args.kwargs
    assert (kwargs["project_id"], kwargs["organization_id"]) == ("p1", "org")
    body = response.json()
    assert body["lineage_available"] is True and body["unresolved_ports"] == []
    group = body["groups"][0]
    assert (group["kind"], group["field_name"], group["dataset_location"], group["override_count"]) == (
        "dataset_field", "id", "main.public.customers @ db:5432", 1,
    )
    occurrence = group["occurrences"][0]
    assert (occurrence["depth"], occurrence["is_override"], occurrence["description_provenance"]) == (2, True, "declared")
    assert occurrence["description_source"]["key"] == "node:n1:output:customer_id"
    row = body["rows"][0]
    assert (row["id"], row["name"], row["is_rename"], row["renamed_from"], row["node_count"]) == (
        "node:n1:output:customer_id", "customer_id", True, "id", 1,
    )
    assert row["targets"] == [{"scope": "project", "node_id": "n1", "port": "output", "column": "customer_id", "dataset_id": None, "field_id": None, "field_name": None}]
    harness.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_patch_columns_writes_then_returns_fields_of_the_written_port(harness):
    payload = {"fields": [{"column": "score", "description": "Скоринг"}, {"column": "old", "description": None}]}
    async with harness.client as client:
        response = await client.patch("/projects/p1/lineage/nodes/n1/columns", json=payload, headers={"X-Language": "ru"})
        assert response.status_code == 200, response.text

        write_kwargs = harness.use_cases.set_node_column_descriptions.execute.await_args.kwargs
        assert (write_kwargs["project_id"], write_kwargs["node_id"], write_kwargs["port"], write_kwargs["actor_user_id"]) == ("p1", "n1", None, "u1")
        assert write_kwargs["changes"] == (ColumnDescriptionChange("score", "Скоринг"), ColumnDescriptionChange("old", None))
        read_kwargs = harness.use_cases.get_node_fields.execute.await_args.kwargs
        assert (read_kwargs["port"], read_kwargs["locale"]) == ("df_out", "ru"), "the response shows the port that was written"
        assert response.json()["fields"][0]["name"] == "customer_id"
        assert response.json()["orphaned_annotations"] == []
        harness.session.commit.assert_awaited_once()

        missing_key = await client.patch("/projects/p1/lineage/nodes/n1/columns", json={"fields": [{"column": "score"}]})
        assert missing_key.status_code == 422
        empty = await client.patch("/projects/p1/lineage/nodes/n1/columns", json={"fields": []})
        assert empty.status_code == 422

        harness.use_cases.set_node_column_descriptions.execute.side_effect = LineageNodePortNotFoundError("no node")
        not_found = await client.patch("/projects/p1/lineage/nodes/ghost/columns", json=payload)
        assert not_found.status_code == 404
        harness.session.commit.assert_awaited_once(), "a failed write is not committed"


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
