import asyncio
import sys
from collections.abc import AsyncGenerator

import pytest
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
from src.modules.user.infra.fastapi.dependencies import (
    get_user_access_only,
    get_user_superadmin_access_only,
)

from .config import app_config, router_config


class _AsyncSessionAdapter:
    def __init__(self, session: Session):
        self._session = session

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


def _override_user_dependencies(app: FastAPI, user: UserModel) -> None:
    from services.gateway.routes.organization import crud as organization_crud
    from services.gateway.routes.project import schedule as project_schedule, task as project_task
    from services.gateway.routes.public.organization import crud as public_organization_crud
    from services.gateway.routes.public.project import task as public_project_task

    dependencies = [
        get_user_superadmin_access_only,
        get_user_access_only,
        get_optional_user_any,
        organization_crud._get_user,
        public_organization_crud._get_user,
        project_schedule._get_user,
        project_task._get_user,
        public_project_task._get_user,
    ]
    for dependency in dependencies:
        app.dependency_overrides[dependency] = lambda user=user: user


@pytest.fixture(scope="session")
def router_prefix() -> str:
    """Возвращает префикс маршрутизатора для тестов."""
    return "/api"


@pytest.fixture(scope="function")
async def auth_app(
        app_config,
        router_config,
        db_session: Session,
) -> FastAPI:
    """Создает экземпляр FastAPI для тестов."""

    def override_get_db():
        yield db_session

    app = AuthApp(
        app_config=app_config,
        router_config=router_config,
    )

    app.dependency_overrides[get_db] = override_get_db

    return app


@pytest.fixture(scope="function")
async def gateway_client(
    test_user: UserModel,
    monkeypatch,
    db_session: Session,
    router_prefix: str,
    auth_app: FastAPI,
    test_user_email: str,
    test_user_password: str,
) -> AsyncGenerator[AsyncClient, None]:
    # 1) Заставляем gateway-шлюз использовать именно наш AuthApp
    from services.gateway import auth_app as auth_app_module
    monkeypatch.setattr(auth_app_module, "create_auth_app", lambda: auth_app)

    # 2) Импортируем основное приложение
    from services.gateway.main import app

    # 3) Override для get_session (всех main-роутов)
    async def override_get_session():
        yield db_session
    async def override_get_async_session():
        yield _AsyncSessionAdapter(db_session)
    app.dependency_overrides[gateway_get_session] = override_get_session
    app.dependency_overrides[gateway_get_async_session] = override_get_async_session

    # 4) Находим внутри routes Mounted AuthApp и там override для get_db
    def override_get_db():
        yield db_session

    for route in app.router.routes:
        if isinstance(route, Mount) and hasattr(route, "app"):
            route.app.dependency_overrides[usrak_get_db] = override_get_db

    from db_connection.compat.dependencies import get_session as dbconn_get_session
    app.dependency_overrides[dbconn_get_session] = override_get_session

    _override_user_dependencies(app, test_user)

    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testgateway")

    yield client
    await client.aclose()


@pytest.fixture(scope="function")
async def unauthenticated_gateway_client(
    monkeypatch,
    db_session: Session,
    auth_app: FastAPI,
) -> AsyncGenerator[AsyncClient, None]:
    # 1) Заставляем gateway-шлюз использовать именно наш AuthApp
    from services.gateway import auth_app as auth_app_module
    monkeypatch.setattr(auth_app_module, "create_auth_app", lambda: auth_app)

    # 2) Импортируем основное приложение
    from services.gateway.main import app

    # 3) Override для get_session (всех main-роутов)
    async def override_get_session():
        yield db_session
    async def override_get_async_session():
        yield _AsyncSessionAdapter(db_session)

    app.dependency_overrides[gateway_get_session] = override_get_session
    app.dependency_overrides[gateway_get_async_session] = override_get_async_session

    # 4) Находим внутри routes Mounted AuthApp и там override для get_db
    def override_get_db():
        yield db_session

    for route in app.router.routes:
        if isinstance(route, Mount) and hasattr(route, "app"):
            route.app.dependency_overrides[usrak_get_db] = override_get_db

    from db_connection.compat.dependencies import get_session as dbconn_get_session
    app.dependency_overrides[dbconn_get_session] = override_get_session

    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testgateway")

    yield client
    await client.aclose()
