from collections.abc import Callable
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet
from db_connection.application.service import ConnectionService
from db_connection.domain.specs import TypeSpec
from db_connection.fastapi import APISchemaSet, DBConnectionExtension
from db_connection.fastapi.schema_builders import (
    build_connection_create_model,
    build_connection_kind_type,
    build_connection_read_model,
    build_connection_type_type,
    build_connection_update_model,
)
from db_connection.registry import ConnectionRegistry, build_default_registry
from db_connection.runtime import DBConnectionSettings, FernetEncryptionProvider
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from .flow.ownership import DVTConnectionOwnershipResolver
from .flow.policies import DVTAccessPolicy
from .flow.use_cases import ResolveConnectionClientUseCase
from .infra.connectors.dvt_service_files import (
    DVTServiceFilesConnector,
    DVTServiceFilesProperties,
    DVTServiceFilesSecrets,
)
from .infra.connectors.smbprotocol import SMBProtocolConnector
from .infra.connectors.smbprotocol.schemas import SMBProtocolProperties, SMBProtocolSecrets
from .infra.errors import DVTErrorMapper
from .infra.repositories import DVTConnectionRepository
from .infra.schemas import (
    DVTConnectionCreateRequest,
    DVTConnectionReadRequest,
    DVTConnectionUpdateRequest,
)
from .infra.uow import DVTConnectionUnitOfWorkFactory
from .infra.user_repository import ExternalUserRepositoryFactory, SessionScopedUserRepository


@lru_cache
def build_encryption_provider(
    fernet_key: str | bytes | Fernet,
):
    return FernetEncryptionProvider(key=fernet_key)


def build_db_connection_repository(
    session: AsyncSession,
    fernet_key: str | bytes | Fernet,
) -> DVTConnectionRepository:
    return DVTConnectionRepository(
        session=session,
        encryption_provider=build_encryption_provider(fernet_key),
    )


def build_registry() -> ConnectionRegistry:
    registry = build_default_registry()
    registry.register_type(
        TypeSpec(
            name="dvt_service_files",
            kind="file",
            properties_model=DVTServiceFilesProperties,
            secrets_model=DVTServiceFilesSecrets,
            public_model=DVTServiceFilesProperties,
            connector_factory=DVTServiceFilesConnector,
            capabilities={"check", "client"},
        )
    )
    registry.register_type(
        TypeSpec(
            name="smbprotocol",
            kind="file",
            properties_model=SMBProtocolProperties,
            secrets_model=SMBProtocolSecrets,
            public_model=SMBProtocolProperties,
            connector_factory=SMBProtocolConnector,
            capabilities={"check", "client"},
        )
    )
    return registry


def build_api_schema_set():
    registry = build_registry()
    return APISchemaSet(
        create=build_connection_create_model(registry, DVTConnectionCreateRequest),
        read=build_connection_read_model(registry, DVTConnectionReadRequest),
        update=build_connection_update_model(registry, DVTConnectionUpdateRequest),
        connection_kind=build_connection_kind_type(registry),
        connection_type=build_connection_type_type(registry),
    )


def build_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def build_db_connection_user_repository(
    session_factory: async_sessionmaker[AsyncSession],
    user_repository_factory: ExternalUserRepositoryFactory,
) -> SessionScopedUserRepository:
    return SessionScopedUserRepository(
        session_factory=session_factory,
        user_repository_factory=user_repository_factory,
    )


def build_uow_factory(
    engine: AsyncEngine,
    fernet_key: str | bytes | Fernet,
) -> DVTConnectionUnitOfWorkFactory:
    return DVTConnectionUnitOfWorkFactory(
        build_session_factory(engine),
        encryption_provider=build_encryption_provider(fernet_key),
    )


def build_connection_service(
    engine: AsyncEngine,
    fernet_key: str | bytes | Fernet,
    user_repository_factory: ExternalUserRepositoryFactory,
    *,
    max_connections: int | None = None,
) -> ConnectionService:
    registry = build_registry()
    session_factory = build_session_factory(engine)
    return ConnectionService(
        settings=DBConnectionSettings(max_connections=max_connections),
        registry=registry,
        uow_factory=build_uow_factory(engine, fernet_key),
        access_policy=DVTAccessPolicy(),
        ownership_resolver=DVTConnectionOwnershipResolver(
            user_repository=build_db_connection_user_repository(
                session_factory=session_factory,
                user_repository_factory=user_repository_factory,
            ),
        ),
    )


def build_resolve_connection_client_use_case(
    engine: AsyncEngine,
    fernet_key: str | bytes | Fernet,
    user_repository_factory: ExternalUserRepositoryFactory,
    *,
    max_connections: int | None = None,
) -> ResolveConnectionClientUseCase:
    registry = build_registry()
    session_factory = build_session_factory(engine)
    service = ConnectionService(
        settings=DBConnectionSettings(max_connections=max_connections),
        registry=registry,
        uow_factory=build_uow_factory(engine, fernet_key),
        access_policy=DVTAccessPolicy(),
        ownership_resolver=DVTConnectionOwnershipResolver(
            user_repository=build_db_connection_user_repository(
                session_factory=session_factory,
                user_repository_factory=user_repository_factory,
            ),
        ),
    )
    return ResolveConnectionClientUseCase(
        service=service,
        registry=registry,
    )


def build_db_connection_extension(
    engine: AsyncEngine,
    fernet_key: str | bytes | Fernet,
    user_repository_factory: ExternalUserRepositoryFactory,
    max_connections: int | None = None,
    get_actor_dependency: Callable[..., Any] | None = None,
) -> DBConnectionExtension:
    uow_factory = build_uow_factory(engine, fernet_key)
    session_factory = build_session_factory(engine)
    registry = build_registry()

    builder = (
        DBConnectionExtension.builder()
        .with_registry(registry)
        .with_uow_factory(uow_factory)
        .with_max_connections(max_connections)
        .with_access_policy(DVTAccessPolicy())
        .with_ownership_resolver(
            DVTConnectionOwnershipResolver(
                user_repository=build_db_connection_user_repository(
                    session_factory=session_factory,
                    user_repository_factory=user_repository_factory,
                ),
            )
        )
        .with_error_mapper(DVTErrorMapper())
        .with_api_schemas(build_api_schema_set())
    )

    if get_actor_dependency is not None:
        builder = builder.with_actor_dependency(get_actor_dependency)

    return builder.build()
