from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.gateway.routes.impl.db_catalog import impl as public_catalog
from services.gateway.routes.internal.ai_mcp import data

from src.modules.db_catalog.domain import (
    CatalogCacheStatus,
    CatalogColumn,
    CatalogResponse,
    CatalogResult,
    CatalogTableDetails,
    CatalogTableKind,
    CatalogTableSummary,
)


@pytest.mark.asyncio
async def test_public_catalog_and_mcp_return_identical_source_comments(monkeypatch):
    table = CatalogTableDetails(
        name="orders",
        schema_name="analytics",
        kind=CatalogTableKind.TABLE,
        comment="Заказы\nПродажи",
        columns=(CatalogColumn(name="id", ordinal=1, dtype="INT", comment="Номер заказа"),),
    )
    now = datetime.now(UTC)
    response = CatalogResponse(
        result=CatalogResult(
            table=table,
            items=(
                CatalogTableSummary(
                    name=table.name,
                    kind=table.kind,
                    schema_name=table.schema_name,
                    comment=table.comment,
                ),
            ),
        ),
        dialect="postgresql",
        catalog_version="v",
        loaded_at=now,
        expires_at=now + timedelta(seconds=60),
        cache_status=CatalogCacheStatus.HIT,
    )
    cases = SimpleNamespace(
        get_table=SimpleNamespace(execute=AsyncMock(return_value=response)),
        list_tables=SimpleNamespace(execute=AsyncMock(return_value=response)),
    )
    monkeypatch.setattr(
        data,
        "get_accessible_connection",
        AsyncMock(
            return_value=SimpleNamespace(kind="sql"),
        ),
    )
    monkeypatch.setattr(data, "build_catalog_actor", lambda user: "actor")
    monkeypatch.setattr(data, "get_catalog_use_cases", lambda redis: cases)
    monkeypatch.setattr(public_catalog, "_actor", lambda user: "actor")
    monkeypatch.setattr(public_catalog, "_use_cases", lambda redis: cases)
    params = {"connection_id": "c", "table_name": "orders", "schema_name": "analytics"}
    mcp_detail = await data.get_database_table(
        principal=SimpleNamespace(user=object()),
        redis=object(),
        **params,
    )
    public_detail = await public_catalog.get_table(user=object(), redis=object(), **params)
    assert public_detail.item.model_dump() == mcp_detail["item"]
    assert mcp_detail["item"]["comment"] == table.comment
    assert mcp_detail["item"]["columns"][0]["comment"] == table.columns[0].comment
    mcp_page = await data.browse_database(
        principal=SimpleNamespace(user=object()),
        redis=object(),
        connection_id="c",
        level="tables",
        schema_name="analytics",
    )
    public_page = await public_catalog.list_tables(
        user=object(),
        redis=object(),
        connection_id="c",
        schema_name="analytics",
    )
    assert [item.model_dump() for item in public_page.items] == mcp_page["items"]
    assert mcp_page["items"][0]["comment"] == table.comment
