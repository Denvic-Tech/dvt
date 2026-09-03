from functools import lru_cache

from db_connection import AccessDeniedError, ConnectionNotFoundError
from sqlalchemy.ext import asyncio as asa

from core.db.connect.sqlalchemy_url import split_backend_and_driver
from core.types import DBCatalogCapabilities, DBMetadata

from src.db import async_engine
from src.logger import logger
from src.modules.db_connection import (
    build_connection_service,
    build_resolve_connection_client_use_case,
)
from src.modules.user import build_get_user_by_id_use_case
from src.modules.user.flow.exceptions import UserNotFoundError
from src.modules.user.infra.db_models import UserRecord
from src.modules.user.infra.repositories import SQLAlchemyUserRepository
from src.node_dsl import (
    IO,
    InputField,
    OutputField,
    SqlConnectionOutputBaseNode,
    SqlConnectionRecord,
)
from src.node_dsl.runtime.connections import resolve_sql_connection_url

import config


@lru_cache
def _build_connection_service():
    return build_connection_service(
        engine=async_engine,
        fernet_key=config.SECURITY.FERNET_KEY,
        user_repository_factory=SQLAlchemyUserRepository,
    )


def _catalog_capabilities(dialect: str) -> DBCatalogCapabilities:
    normalized = dialect.lower()
    return DBCatalogCapabilities(
        supports_databases=normalized in {
            "postgresql", "mysql", "mariadb", "mssql", "sqlserver", "clickhouse"
        },
        supports_schemas=normalized in {"postgresql", "mssql", "sqlserver", "oracle", "sqlite"},
    )


class GetExistDBConnection(SqlConnectionOutputBaseNode):
    TITLE = "DB Connection"
    EMOJI = "🔌"
    CATEGORY = "Connections"
    CACHABLE = False

    # --- Inputs ---
    connection_id: IO.DB_CONNECTION_ID = InputField()

    # --- Outputs ---
    connection: SqlConnectionRecord = OutputField()

    async def _get_user(self) -> UserRecord:
        async with asa.AsyncSession(async_engine) as session:
            use_case = build_get_user_by_id_use_case(session)
            return await use_case.execute(user_id=self.user_id)

    async def _get_connection_from_db(self) -> SqlConnectionRecord:
        try:
            user = await self._get_user()
            if user is None:
                logger.error(f"No DB connection found with ID {self.connection_id} for user {self._user_id}")
                raise ValueError(f"No DB connection found with ID {self.connection_id} for user {self._user_id}")

            record = await _build_connection_service().get(self.connection_id, actor=user)
        except (UserNotFoundError, AccessDeniedError, ConnectionNotFoundError) as e:
            logger.error(f"No DB connection found with ID {self.connection_id} for user {self._user_id}")
            raise ValueError(f"No DB connection found with ID {self.connection_id} for user {self._user_id}") from e

        if str(record.kind).lower() == "sql":
            return SqlConnectionRecord(record)

        logger.error(f"Connection with ID {self.connection_id} is not a SQL connection.")
        raise TypeError(f"Connection with ID {self.connection_id} is not a SQL connection.")

    async def process(self):
        self.connection = await self._get_connection_from_db()

    async def infer_metadata(self):
        connection = getattr(self, "connection", None)
        if not isinstance(connection, SqlConnectionRecord):
            connection = await self._get_connection_from_db()

        url = resolve_sql_connection_url(connection)
        backend, _driver = split_backend_and_driver(url)
        revision = getattr(connection.record, "updated_at", None)
        return {
            "connection": DBMetadata(
                connection_id=connection.id,
                connection_revision=revision.isoformat() if revision is not None else None,
                catalog_mode="lazy",
                catalog_capabilities=_catalog_capabilities(backend),
                dialect=backend,
                database_name=url.database,
                databases=[],
                schemas=[],
                tables=[],
            )
        }
