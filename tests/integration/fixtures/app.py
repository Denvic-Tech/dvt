from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.routing import Mount
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session
from usrak import AuthApp
from usrak.core.db import get_db, get_db as usrak_get_db
from usrak.core.dependencies.user import get_optional_user_any

from src.db.session import (
    get_async_session as gateway_get_async_session,
    get_session as gateway_get_session,
)
from src.modules.user.infra.db_models import UserRecord as UserModel
from src.modules.user.infra.fastapi.dependencies import get_user_access_only

class _AsyncSessionAdapter:
    def __init__(self, session: Session):
        self._session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def add(self, instance):
        self._session.add(instance)

    async def commit(self):
        self._session.commit()

    async def refresh(self, instance):
        self._session.refresh(instance)

    async def flush(self, objects=None):
        self._session.flush(objects)

    async def execute(self, statement):
        return self._session.execute(statement)

    async def get(self, entity, ident):
        return self._session.get(entity, ident)

    async def delete(self, instance):
        self._session.delete(instance)

    async def rollback(self):
        self._session.rollback()

    async def close(self):
        # The underlying session lifecycle belongs to the fixture.
        return None

    def in_transaction(self):
        return self._session.in_transaction()


class _GatewayDBConnectionSessionFactory:
    def __init__(self, context: "_GatewayFixtureContext"):
        self._context = context

    def __call__(self) -> _AsyncSessionAdapter:
        if self._context.db_session is None:
            raise RuntimeError("Test DB session is not configured")
        return _AsyncSessionAdapter(self._context.db_session)


@dataclass
class _GatewayFixtureContext:
    db_session: Session | None = None
    user: UserModel | None = None


@pytest.fixture(scope="session")
def router_prefix() -> str:
    """Возвращает префикс маршрутизатора для тестов."""
    return "/api"


@pytest.fixture(scope="session")
def gateway_fixture_context() -> _GatewayFixtureContext:
    return _GatewayFixtureContext()


@pytest.fixture(scope="session")
def auth_app(
        app_config,
        router_config,
        gateway_fixture_context: _GatewayFixtureContext,
) -> FastAPI:
    """Создает экземпляр FastAPI для тестов."""

    def override_get_db():
        if gateway_fixture_context.db_session is None:
            raise RuntimeError("Test DB session is not configured")
        yield gateway_fixture_context.db_session

    app = AuthApp(
        app_config=app_config,
        router_config=router_config,
    )

    app.dependency_overrides[get_db] = override_get_db

    return app


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def gateway_app(
    redis_container,
    auth_app: FastAPI,
    gateway_fixture_context: _GatewayFixtureContext,
) -> AsyncGenerator[FastAPI, None]:
    from redis.asyncio import Redis

    from services.gateway import auth_app as auth_app_module
    from services.gateway.deps.redis import get_redis_bytes
    from services.gateway.routes.db_connections import main_db_connections_ext
    from services.gateway.routes.public.router import public_db_connections_ext

    original_create_auth_app = auth_app_module.create_auth_app
    auth_app_module.create_auth_app = lambda: auth_app
    from services.gateway.main import app

    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(redis_container.port)

    async def override_get_redis():
        test_redis = Redis(host=host, port=port, decode_responses=False)
        try:
            yield test_redis
        finally:
            await test_redis.aclose()

    async def override_get_session():
        if gateway_fixture_context.db_session is None:
            raise RuntimeError("Test DB session is not configured")
        yield gateway_fixture_context.db_session

    async def override_get_async_session():
        if gateway_fixture_context.db_session is None:
            raise RuntimeError("Test DB session is not configured")
        yield _AsyncSessionAdapter(gateway_fixture_context.db_session)

    def override_get_db():
        if gateway_fixture_context.db_session is None:
            raise RuntimeError("Test DB session is not configured")
        yield gateway_fixture_context.db_session

    app.dependency_overrides[gateway_get_session] = override_get_session
    app.dependency_overrides[gateway_get_async_session] = override_get_async_session

    for route in app.router.routes:
        if isinstance(route, Mount) and hasattr(route, "app"):
            route.app.dependency_overrides[usrak_get_db] = override_get_db

    db_connection_session_factory = _GatewayDBConnectionSessionFactory(gateway_fixture_context)
    for extension in (main_db_connections_ext, public_db_connections_ext):
        extension.runtime.uow_factory._session_factory = db_connection_session_factory
        extension.runtime.service._uow_factory._session_factory = db_connection_session_factory
        extension.runtime.service._ownership_resolver._user_repository._session_factory = (
            db_connection_session_factory
        )

    app.dependency_overrides[get_redis_bytes] = override_get_redis

    try:
        yield app
    finally:
        app.dependency_overrides.pop(gateway_get_session, None)
        app.dependency_overrides.pop(gateway_get_async_session, None)
        app.dependency_overrides.pop(get_redis_bytes, None)
        app.dependency_overrides.pop(get_user_access_only, None)
        app.dependency_overrides.pop(get_optional_user_any, None)
        for route in app.router.routes:
            if isinstance(route, Mount) and hasattr(route, "app"):
                route.app.dependency_overrides.pop(usrak_get_db, None)
        gateway_fixture_context.db_session = None
        gateway_fixture_context.user = None
        auth_app_module.create_auth_app = original_create_auth_app


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def gateway_http_client(gateway_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    client = AsyncClient(transport=ASGITransport(app=gateway_app), base_url="http://testgateway")
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture(scope="function")
async def gateway_client(
    test_user: UserModel,
    test_db_session: Session,
    gateway_app: FastAPI,
    gateway_http_client: AsyncClient,
    gateway_fixture_context: _GatewayFixtureContext,
) -> AsyncGenerator[AsyncClient, None]:
    gateway_fixture_context.db_session = test_db_session
    gateway_fixture_context.user = test_user
    from services.gateway.routes.project import schedule as project_schedule
    gateway_app.dependency_overrides[get_user_access_only] = (
        lambda: gateway_fixture_context.user
    )
    gateway_app.dependency_overrides[get_optional_user_any] = lambda: gateway_fixture_context.user
    gateway_app.dependency_overrides[project_schedule._get_user] = lambda: gateway_fixture_context.user

    yield gateway_http_client

    gateway_app.dependency_overrides.pop(get_user_access_only, None)
    gateway_app.dependency_overrides.pop(get_optional_user_any, None)
    gateway_app.dependency_overrides.pop(project_schedule._get_user, None)
    gateway_fixture_context.user = None
    gateway_fixture_context.db_session = None


@pytest.fixture(scope="function")
async def unauthenticated_gateway_client(
    db_session: Session,
    gateway_app: FastAPI,
    gateway_http_client: AsyncClient,
    gateway_fixture_context: _GatewayFixtureContext,
) -> AsyncGenerator[AsyncClient, None]:
    gateway_fixture_context.db_session = db_session
    gateway_app.dependency_overrides.pop(get_user_access_only, None)
    gateway_app.dependency_overrides.pop(get_optional_user_any, None)

    yield gateway_http_client

    gateway_fixture_context.db_session = None
