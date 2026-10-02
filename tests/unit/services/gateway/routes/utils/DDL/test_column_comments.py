from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from services.gateway.routes.utils.DDL import table


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "worker"),
    [
        ("create_table", "create_table_from_connection_string"),
        ("recreate_table", "_recreate_table_request"),
        ("apply_column_actions", "_apply_table_column_actions_request"),
    ],
)
@pytest.mark.parametrize("fails", [False, True])
async def test_catalog_is_invalidated_even_after_partial_ddl(monkeypatch, endpoint, worker, fails):
    invalidate = AsyncMock()
    execute = Mock(side_effect=ValueError("DDL failed") if fails else None, return_value="ok")
    monkeypatch.setattr(table, "invalidate_ddl_catalog", invalidate)
    monkeypatch.setattr(table, worker, execute)
    request = SimpleNamespace(connection_id="test", dry_run=False)
    if fails:
        with pytest.raises(ValueError, match="DDL failed"):
            await getattr(table, endpoint)(request, object(), object())
    else:
        assert await getattr(table, endpoint)(request, object(), object()) == "ok"
    invalidate.assert_awaited_once()


@pytest.mark.asyncio
async def test_dry_run_does_not_invalidate_catalog(monkeypatch):
    invalidate = AsyncMock()
    monkeypatch.setattr(table, "invalidate_ddl_catalog", invalidate)
    monkeypatch.setattr(table, "_apply_table_column_actions_request", Mock(return_value="preview"))
    request = SimpleNamespace(connection_id="test", dry_run=True)
    assert await table.apply_column_actions(request, object(), object()) == "preview"
    invalidate.assert_not_awaited()
