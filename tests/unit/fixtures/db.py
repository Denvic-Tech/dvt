import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

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


def _create_test_tables(engine: sa.Engine) -> None:
    """Create sqlite-only tables for metadata tests."""
    metadata = sa.MetaData()

    sa.Table(
        "sample_users",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    sa.Table(
        "sample_orders",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("rating", sa.Float, nullable=True),
    )

    sa.Table(
        "sample_events",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("payload", sa.JSON, nullable=True),
        sa.Column("event_date", sa.Date, nullable=False),
        sa.Column("event_time", sa.Time, nullable=True),
    )

    metadata.create_all(engine)


@pytest.fixture(scope="session")
def test_db_engine() -> sa.Engine:
    engine = sa.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    _create_test_tables(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def test_db_session(test_db_engine) -> Session:
    connection = test_db_engine.connect()
    transaction = connection.begin()

    connection.execute(sa.text("PRAGMA foreign_keys=ON"))

    Session = sessionmaker(bind=connection, expire_on_commit=False)
    session = Session()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="function")
async def async_test_db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )

    # Создаём таблицы на этом же соединении
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await conn.run_sync(_create_test_tables)

    yield engine
    await engine.dispose()


@pytest.fixture(scope="function")
async def async_test_db_session(async_test_db_engine):
    async with async_test_db_engine.connect() as conn:
        await conn.execute(sa.text("PRAGMA foreign_keys=ON"))
        # Используем nested transaction, чтобы не конфликтовать с уже открытой
        async with conn.begin_nested() as transaction:
            AsyncSessionLocal = sessionmaker(
                bind=conn, class_=AsyncSession, expire_on_commit=False
            )
            async with AsyncSessionLocal() as session:
                yield session
            # rollback nested transaction после теста
            await transaction.rollback()