from db_connection.application import ConnectionUnitOfWork, ConnectionUnitOfWorkFactory
from db_connection.runtime.encryption import FernetEncryptionProvider
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .repositories import DVTConnectionRepository


class DVTConnectionUnitOfWork(ConnectionUnitOfWork):
    """UoW для DVT, владеющий одной AsyncSession."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        encryption_provider: FernetEncryptionProvider,
    ) -> None:
        self._session = session
        self._connections = DVTConnectionRepository(
            session,
            encryption_provider=encryption_provider,
        )

    @property
    def connections(self) -> DVTConnectionRepository:
        return self._connections

    async def __aenter__(self) -> "DVTConnectionUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if exc is not None and self._session.in_transaction():
                await self.rollback()
        finally:
            await self._session.close()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


class DVTConnectionUnitOfWorkFactory(ConnectionUnitOfWorkFactory):
    """Фабрика request-scoped UoW для DVT."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        encryption_provider: FernetEncryptionProvider,
    ) -> None:
        self._session_factory = session_factory
        self._encryption_provider = encryption_provider

    def __call__(self) -> DVTConnectionUnitOfWork:
        return DVTConnectionUnitOfWork(
            self._session_factory(),
            encryption_provider=self._encryption_provider,
        )
