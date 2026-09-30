from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from services.gateway.main import app
from services.gateway.routes.utils.DDL import table

from src.exceptions import ApplyTableColumnActionsError
from src.schemas.http.create_table import ApplyTableColumnActionsRequest


def test_nullable_is_exposed_in_gateway_openapi():
    schema = app.openapi()
    components = schema["components"]["schemas"]
    action_ref = components["ApplyTableColumnActionsRequest"]["properties"]["actions"]["items"]["$ref"]
    action = components[action_ref.rsplit("/", 1)[-1]]["properties"]
    assert "set_column_nullable" in action["type"]["enum"]
    assert {"type": "boolean"} in action["nullable"]["anyOf"]
    operation = schema["paths"]["/utils/ddl/apply-table-column-actions"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ApplyTableColumnActionsRequest"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [False, True])
async def test_unsupported_nullable_uses_existing_error_and_cache_contract(monkeypatch, dry_run):
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool,
                              connect_args={"check_same_thread": False})
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE items (value INT)")
    monkeypatch.setattr(table, "build_engine_from_connection_string", lambda **kw: engine)
    invalidate = AsyncMock()
    monkeypatch.setattr(table, "invalidate_ddl_catalog", invalidate)
    request = ApplyTableColumnActionsRequest(
        connection_id="sqlite://", table_name="items", dry_run=dry_run,
        actions=[{"type": "set_column_nullable", "column_name": "value", "nullable": False}],
    )
    with pytest.raises(ApplyTableColumnActionsError) as error:
        await table.apply_column_actions(request, object(), object())
    assert error.value.detail["code"] == "APPLY_TABLE_COLUMN_ACTIONS_ERROR"
    assert "not supported for sqlite" in error.value.detail["detail"]
    assert invalidate.await_count == (0 if dry_run else 1)
