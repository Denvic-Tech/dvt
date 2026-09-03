from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
import sqlalchemy.ext.asyncio as asa
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session, sessionmaker

from src.models import (
    AIAnalysisRequestRecord,  # noqa: F403
    ExtensionRecord,  # noqa: F403
    LogRecord,  # noqa: F403
    OrganizationRecord,  # noqa: F403
    QueueTopicRecord,  # noqa: F403
    SQLModel,
    UsersTokenRecord,  # noqa: F403
)
from src.modules.app_settings.infra.db_models import (  # noqa: F403
    AppSettingChangeRecord,
    AppSettingValueRecord,
)
from src.modules.db_connection.infra.db_models import DVTStoredConnectionRecord  # noqa: F403
from src.modules.file_storage.infra.db_models import DVTServiceFileObjectRecord  # noqa: F403
from src.modules.pipeline_graph.infra.db_models import (  # noqa: F403
    GraphEdgeRecord,
    GraphNodeRecord,
    SubgraphRecord,
)
from src.modules.project.infra.db_models import (
    ProjectFolderRecord,  # noqa: F403
    ProjectRecord,  # noqa: F403
    ProjectScheduleRecord,  # noqa: F403
    ProjectScheduleRunRecord,  # noqa: F403
)
from src.modules.task_execution.infra.db_models import (  # noqa: F403
    TaskDispatchOutboxRecord,
    TaskRecord,
)
from src.modules.user.infra.db_models import UserRecord  # noqa: F403
from src.utils.waiting import wait_for_db

from .containers import postgres_container  # noqa: F401
from .dvt_prod_containers import dvt_postgres_container  # noqa: F401


def make_async_url(sync_url: sa.URL) -> sa.URL:
    return sync_url.set(drivername="postgresql+psycopg")


def _stamp_database_at_alembic_head(engine: sa.Engine) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    alembic_config = Config(str(repo_root / "alembic.ini"))
    script_directory = ScriptDirectory.from_config(alembic_config)

    with engine.begin() as connection:
        MigrationContext.configure(connection).stamp(script_directory, "head")


@pytest.fixture(scope="session")
def test_db_engine(postgres_container) -> Generator[sa.Engine]:
    engine = sa.create_engine(postgres_container.get_connection_url())

    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    try:
        yield engine
    finally:
        SQLModel.metadata.drop_all(engine)
        engine.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_db_async_engine(
    test_db_engine: sa.Engine,
) -> AsyncGenerator[AsyncEngine]:
    engine = asa.create_async_engine(
        make_async_url(test_db_engine.url),
        pool_pre_ping=True,
    )

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture(scope="function")
def test_db_session(
    test_db_engine: sa.Engine,
) -> Generator[Session]:
    connection = test_db_engine.connect()
    transaction = connection.begin()

    SessionLocal = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    session = SessionLocal()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def test_db_async_session(
    test_db_async_engine: AsyncEngine,
) -> AsyncGenerator[asa.AsyncSession]:
    connection = await test_db_async_engine.connect()
    transaction = await connection.begin()

    AsyncSessionLocal = asa.async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    session = AsyncSessionLocal()

    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest.fixture(scope="session")
def test_dvt_db_engine(dvt_postgres_container) -> Generator[sa.Engine, Any]:
    db_url = f"postgresql+psycopg://postgres:postgres@{dvt_postgres_container.get_container_host_ip()}:{dvt_postgres_container.get_exposed_port(5432)}/DVT"
    engine = sa.create_engine(db_url)
    with Session(bind=engine) as session:
        wait_for_db(session)
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    _stamp_database_at_alembic_head(engine)
    try:
        yield engine
    finally:
        SQLModel.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture(scope="function")
def test_dvt_db_session(test_dvt_db_engine) -> Generator[Session, Any]:
    connection = test_dvt_db_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()

    # Keep one outer transaction per test and restart SAVEPOINTs after commits inside the code under test.
    session.begin_nested()

    def _restart_savepoint(sess: Session, trans) -> None:  # pragma: no cover
        parent = getattr(trans, "_parent", None)
        if trans.nested and parent is not None and not parent.nested:
            sess.begin_nested()

    event.listen(session, "after_transaction_end", _restart_savepoint)

    try:
        yield session
    finally:
        event.remove(session, "after_transaction_end", _restart_savepoint)
        session.close()
        transaction.rollback()
        connection.close()



@pytest.fixture(scope="session")
def test_db_url(postgres_container) -> str:
    """Возвращает строку подключения к тестовой БД"""
    return postgres_container.get_connection_url()

@pytest.fixture()
def db_session(test_db_session):
    return test_db_session
