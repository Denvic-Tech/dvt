import pytest

from services.gateway.deps.redis import get_redis_bytes
from services.gateway.routes.utils.DDL import database, schema, table
from services.gateway.routes.utils.DDL.connection import ResolvedDDLConnection


@pytest.fixture(autouse=True)
def stub_stored_ddl_connections(monkeypatch):
    """Keep DDL route tests focused on DDL while using the new opaque reference contract."""

    async def resolve(connection_id, _user):
        return ResolvedDDLConnection(
            connection_id=connection_id,
            connection_string=connection_id,
        )

    async def invalidate(*_args, **_kwargs):
        return None

    async def redis_override():
        yield object()

    for module in (database, schema, table):
        monkeypatch.setattr(module, "resolve_ddl_connection", resolve)
        monkeypatch.setattr(module, "invalidate_ddl_catalog", invalidate)

    from services.gateway.main import app

    app.dependency_overrides[get_redis_bytes] = redis_override
    yield
    app.dependency_overrides.pop(get_redis_bytes, None)
