from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.gateway.main import app
from services.gateway.routes.impl.partitioning_advice import (
    PartitioningAdviceError,
    PartitioningAdviceRequest,
    PartitioningAdviceResponse,
    impl,
    suggest_read_partitioning,
)

from src.modules.user.infra.fastapi.dependencies import get_user_access_only

ROWS = 3_000


@pytest.fixture
def sqlite_url(tmp_path) -> str:
    url = f"sqlite:///{(tmp_path / 'advice.db').as_posix()}"
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE sales (id INTEGER PRIMARY KEY, store INTEGER, sold_on DATE)"
        )
        conn.execute(
            sa.text("INSERT INTO sales VALUES (:id, :store, :sold_on)"),
            [
                {
                    "id": idx,
                    "store": 1 if idx <= 2_000 else idx,
                    "sold_on": f"2025-01-{1 + idx % 28:02d}",
                }
                for idx in range(1, ROWS + 1)
            ],
        )
    engine.dispose()
    return url


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"table_name": "sales", "sql_code": "SELECT 1"},
        {"sql_code": "SELECT 1", "schema_name": "public"},
        {"table_name": "sales", "unexpected": True},
        {"table_name": "sales", "candidate_limit": 0},
    ],
)
def test_request_requires_one_relation_and_rejects_unknown_fields(payload):
    with pytest.raises(ValidationError):
        PartitioningAdviceRequest.model_validate(payload)


async def test_table_advice_round_trips_as_json_with_node_field_names(sqlite_url):
    response = await suggest_read_partitioning(
        sqlite_url, PartitioningAdviceRequest(table_name="sales", npartitions=10)
    )

    payload = json.loads(response.model_dump_json())
    assert PartitioningAdviceResponse.model_validate(payload) == response
    assert payload["relation"]["total_rows"] == ROWS
    assert payload["sizing"]["target_npartitions"] == 10
    statistics = {item["name"]: item for item in payload["statistics"]}
    assert statistics["store"]["max_repeat"] == 2_000
    assert statistics["sold_on"]["min_value"] == "2025-01-01"
    best = payload["recommendations"][0]
    assert best["partition_col"] == "id"
    assert best["partition_grouping"] == {"mode": "range"}
    assert best["npartitions"] == 10
    assert best["max_rows_per_partition"] >= 100_000
    assert [item["name"] for item in payload["excluded"]] == []


async def test_query_mode_follows_the_readonly_sql_policy(sqlite_url):
    with pytest.raises(PartitioningAdviceError) as raised:
        await suggest_read_partitioning(
            sqlite_url, PartitioningAdviceRequest(sql_code="SELECT * FROM sales")
        )
    assert (raised.value.status_code, raised.value.code) == (422, "UNSAFE_SQL")

    # Validation happens before any connection to the source is opened.
    with pytest.raises(PartitioningAdviceError) as raised:
        await suggest_read_partitioning(
            "postgresql+psycopg2://user:secret@127.0.0.1:1/db",
            PartitioningAdviceRequest(sql_code="DELETE FROM sales"),
        )
    assert raised.value.code == "UNSAFE_SQL"


async def test_unknown_candidate_is_reported_without_driver_details(sqlite_url):
    with pytest.raises(PartitioningAdviceError) as raised:
        await suggest_read_partitioning(
            sqlite_url, PartitioningAdviceRequest(table_name="sales", columns=["missing"])
        )
    assert raised.value.code == "INVALID_RELATION"
    assert "'missing' was not found" in raised.value.message


def _user() -> object:
    return SimpleNamespace(id="u1")


def test_route_returns_advice_and_maps_errors(sqlite_url, monkeypatch):
    async def resolve(connection_id, user):
        return SimpleNamespace(connection_id=connection_id, connection_string=sqlite_url)

    monkeypatch.setattr(impl, "resolve_ddl_connection", resolve)
    app.dependency_overrides[get_user_access_only] = _user
    try:
        client = TestClient(app)
        ok = client.post(
            "/db-connections/c1/partitioning-advice",
            json={"table_name": "sales", "columns": ["store"], "npartitions": 10},
        )
        failed = client.post(
            "/db-connections/c1/partitioning-advice", json={"sql_code": "SELECT 1"}
        )
    finally:
        app.dependency_overrides.pop(get_user_access_only, None)

    assert ok.status_code == 200
    assert ok.json()["statistics"][0]["name"] == "store"
    assert failed.status_code == 422
    assert failed.json()["description"]["code"] == "UNSAFE_SQL"


def test_openapi_exposes_the_advice_route():
    schema = app.openapi()
    operation = schema["paths"]["/db-connections/{connection_id}/partitioning-advice"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/PartitioningAdviceRequest"
    )
    recommendation = schema["components"]["schemas"]["PartitionRecommendationSchema"]
    assert {"partition_col", "partition_grouping", "npartitions", "max_rows_per_partition"} <= set(
        recommendation["properties"]
    )
