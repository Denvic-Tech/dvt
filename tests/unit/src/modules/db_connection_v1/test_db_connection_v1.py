from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from db_connection import AccessDeniedError, ValidationFailedError
from db_connection.connectors.base import Connector
from db_connection.domain import (
    ConnectionCheckResult,
    ConnectionDraft,
    ConnectionListQuery,
    ConnectionPatch,
    ConnectionRecord,
    ValidatedConnection,
)
from db_connection.domain.drivers import ODBCDriverOptions
from db_connection.domain.specs import KindSpec, TypeSpec
from db_connection.registry.base import ConnectionRegistry
from pydantic import BaseModel
from usrak.core.security import hash_password

from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.user.infra.db_models import UserRecord as UserModel
from src.modules.db_connection.facade import (
    build_db_connection_extension,
    build_db_connection_repository,
    build_registry,
    build_resolve_connection_client_use_case,
)
from src.modules.db_connection.flow.ownership import DVTConnectionOwnershipResolver
from src.modules.db_connection.flow.policies import DVTAccessPolicy
from src.modules.db_connection.flow.use_cases import (
    ResolveConnectionClientUseCase,
    ResolvedConnectionClient,
)
from src.modules.db_connection.infra.connectors.smbprotocol import (
    SMBProtocolClient,
    SMBProtocolConnector,
    client as smbprotocol_client_module,
    connector as smbprotocol_connector_module,
)
from src.modules.db_connection.infra.user_repository import SessionScopedUserRepository
from src.modules.user.infra.repositories import SQLAlchemyUserRepository


def _build_actor(*, role: str, organization_id: str, user_id: str) -> SimpleNamespace:
    return SimpleNamespace(role=role, organization_id=organization_id, id=user_id)


def _build_connection_record(
    *,
    organization_id: str,
    user_id: str,
    connection_type: str = "smbprotocol",
    kind: str = "file",
    properties: dict[str, object] | None = None,
    secrets: dict[str, object] | None = None,
) -> ConnectionRecord:
    return ConnectionRecord(
        id="conn-1",
        name="Shared files",
        kind=kind,
        type=connection_type,
        driver=None,
        driver_options=None,
        properties=properties
        or {"host": "fileserver", "port": 445, "share": "shared", "username": "reader"},
        secrets=secrets or {"password": "secret"},
        labels={"env": "test"},
        metadata={"team": "data"},
        extra={
            "organization_id": organization_id,
            "user_id": user_id,
            "scope": "shared",
        },
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _build_draft(
    *,
    organization_id: str | None = None,
    user_id: str | None = None,
    scope: str = "shared",
) -> ConnectionDraft:
    extra: dict[str, object] = {"scope": scope}
    if organization_id is not None:
        extra["organization_id"] = organization_id
    if user_id is not None:
        extra["user_id"] = user_id

    return ConnectionDraft(
        name="Shared files",
        kind="file",
        type="smbprotocol",
        driver=None,
        driver_options=None,
        properties={"host": "fileserver", "port": 445, "share": "shared", "username": "reader"},
        secrets={"password": "secret"},
        labels={"env": "test"},
        metadata={"team": "data"},
        extra=extra,
    )


def _build_validated_connection() -> ValidatedConnection:
    from src.modules.db_connection.infra.connectors.smbprotocol.schemas import SMBProtocolSecrets
    from src.modules.db_connection.infra.connectors.smbprotocol.schemas import SMBProtocolProperties

    return ValidatedConnection(
        name="Shared files",
        kind="file",
        type="smbprotocol",
        driver=None,
        driver_options=None,
        properties=SMBProtocolProperties(host="fileserver", port=445, share="shared", username="reader"),
        secrets=SMBProtocolSecrets(password="secret"),
        labels={},
        metadata={},
        extra={},
    )


async def _create_user(async_test_db_session, *, role: str) -> UserModel:
    organization = OrganizationRecord(name=f"Org {role}")
    async_test_db_session.add(organization)
    await async_test_db_session.commit()
    await async_test_db_session.refresh(organization)

    return await _create_user_in_organization(
        async_test_db_session,
        role=role,
        organization_id=organization.id,
        email_prefix=role,
    )


async def _create_user_in_organization(
    async_test_db_session,
    *,
    role: str,
    organization_id: str,
    email_prefix: str,
) -> UserModel:
    user = UserModel(
        email=f"{email_prefix}-{role}@example.com",
        hashed_password=hash_password("Password123"),
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=role,
        organization_id=organization_id,
    )
    async_test_db_session.add(user)
    await async_test_db_session.commit()
    await async_test_db_session.refresh(user)
    return user


def _build_ownership_resolver(async_test_db_session) -> DVTConnectionOwnershipResolver:
    @asynccontextmanager
    async def _session_scope():
        yield async_test_db_session

    return DVTConnectionOwnershipResolver(
        user_repository=SessionScopedUserRepository(
            session_factory=lambda: _session_scope(),
            user_repository_factory=SQLAlchemyUserRepository,
        )
    )


class _ServiceStub:
    def __init__(self, *, record: ConnectionRecord | None = None, exc: Exception | None = None) -> None:
        self._record = record
        self._exc = exc
        self.calls: list[tuple[str, object]] = []

    async def get(self, connection_id: str, actor=None, **_kwargs):
        self.calls.append((connection_id, actor))
        if self._exc is not None:
            raise self._exc
        return self._record


class _DummyProperties(BaseModel):
    dsn: str


class _DummySecrets(BaseModel):
    token: str | None = None


class _DummyConnector(Connector):
    def __init__(self, client) -> None:
        self.client = client
        self.received: ValidatedConnection | None = None

    async def check(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        return ConnectionCheckResult(name=connection.name, connected=True, message="ok")

    async def get_client(self, connection: ValidatedConnection):
        self.received = connection
        return self.client


def _build_dummy_registry(connector: _DummyConnector, *, capabilities: set[str] | None = None) -> ConnectionRegistry:
    registry = ConnectionRegistry()
    registry.register_kind(KindSpec(name="sql"))
    registry.register_type(
        TypeSpec(
            name="dummy_sql",
            kind="sql",
            properties_model=_DummyProperties,
            secrets_model=_DummySecrets,
            connector_factory=lambda: connector,
            capabilities=capabilities or {"client"},
        )
    )
    return registry


@pytest.mark.asyncio
async def test_access_policy_scopes_regular_user_to_org_and_owner(test_user) -> None:
    policy = DVTAccessPolicy()

    scoped = await policy.scope_list(
        SimpleNamespace(actor=test_user, operation="list"),
        ConnectionListQuery(extra_filters={"scope": "shared"}),
    )

    assert scoped.extra_filters == {
        "scope": "shared",
        "organization_id": test_user.organization_id,
        "user_id": test_user.id,
    }


@pytest.mark.asyncio
async def test_access_policy_allows_admin_to_read_same_org_connection(test_admin_user) -> None:
    policy = DVTAccessPolicy()
    connection = _build_connection_record(
        organization_id=test_admin_user.organization_id,
        user_id="another-user",
    )

    await policy.can_get_one(
        SimpleNamespace(actor=test_admin_user, operation="get", connection_id=connection.id),
        connection,
    )


@pytest.mark.asyncio
async def test_access_policy_rejects_regular_user_for_foreign_connection(test_user) -> None:
    policy = DVTAccessPolicy()
    connection = _build_connection_record(
        organization_id=test_user.organization_id,
        user_id="another-user",
    )

    with pytest.raises(AccessDeniedError):
        await policy.can_get_one(
            SimpleNamespace(actor=test_user, operation="get", connection_id=connection.id),
            connection,
        )


@pytest.mark.asyncio
async def test_access_policy_blocks_regular_user_owner_change(test_user) -> None:
    policy = DVTAccessPolicy()
    connection = _build_connection_record(
        organization_id=test_user.organization_id,
        user_id=test_user.id,
    )

    with pytest.raises(AccessDeniedError):
        await policy.can_update(
            SimpleNamespace(actor=test_user, operation="update", connection_id=connection.id),
            connection,
            ConnectionPatch(extra={"user_id": "other-user"}),
        )


@pytest.mark.asyncio
async def test_access_policy_allows_superadmin_to_target_other_owner(test_superadmin_user, test_user) -> None:
    policy = DVTAccessPolicy()

    await policy.can_create(
        SimpleNamespace(
            actor=test_superadmin_user,
            operation="create",
            payload={
                "organization_id": test_user.organization_id,
                "user_id": test_user.id,
            },
        ),
        _build_draft(
            organization_id=test_user.organization_id,
            user_id=test_user.id,
        ),
    )


@pytest.mark.asyncio
async def test_ownership_resolver_uses_regular_user_actor_owner(async_test_db_session) -> None:
    actor = await _create_user(async_test_db_session, role=DVTDefaultRoles.USER.value)
    resolver = _build_ownership_resolver(async_test_db_session)

    resolved = await resolver.resolve_create(
        SimpleNamespace(actor=actor, operation="create"),
        _build_draft(),
    )

    assert resolved.extra["organization_id"] == actor.organization_id
    assert resolved.extra["user_id"] == actor.id
    assert resolved.extra["scope"] == "shared"


@pytest.mark.asyncio
async def test_ownership_resolver_allows_admin_to_target_same_org_user(async_test_db_session) -> None:
    admin_actor = await _create_user(async_test_db_session, role=DVTDefaultRoles.ADMIN.value)
    resolver = _build_ownership_resolver(async_test_db_session)
    same_org_user = await _create_user_in_organization(
        async_test_db_session,
        role=DVTDefaultRoles.USER.value,
        organization_id=admin_actor.organization_id,
        email_prefix="same-org",
    )

    resolved = await resolver.resolve_create(
        SimpleNamespace(actor=admin_actor, operation="create"),
        _build_draft(user_id=same_org_user.id),
    )

    assert resolved.extra["organization_id"] == admin_actor.organization_id
    assert resolved.extra["user_id"] == same_org_user.id


@pytest.mark.asyncio
async def test_ownership_resolver_rejects_cross_org_user_override(async_test_db_session) -> None:
    admin_actor = await _create_user(async_test_db_session, role=DVTDefaultRoles.ADMIN.value)
    foreign_user = await _create_user(async_test_db_session, role=DVTDefaultRoles.USER.value)
    resolver = _build_ownership_resolver(async_test_db_session)

    with pytest.raises(ValidationFailedError, match="Target user does not belong"):
        await resolver.resolve_create(
            SimpleNamespace(actor=admin_actor, operation="create"),
            _build_draft(user_id=foreign_user.id),
        )


@pytest.mark.asyncio
async def test_ownership_resolver_rejects_missing_user(async_test_db_session) -> None:
    admin_actor = await _create_user(async_test_db_session, role=DVTDefaultRoles.ADMIN.value)
    resolver = _build_ownership_resolver(async_test_db_session)

    with pytest.raises(ValidationFailedError, match="Target user does not belong"):
        await resolver.resolve_create(
            SimpleNamespace(actor=admin_actor, operation="create"),
            _build_draft(user_id="missing-user"),
        )


@pytest.mark.asyncio
async def test_ownership_resolver_patch_preserves_owner_for_non_owner_extra(async_test_db_session) -> None:
    admin_actor = await _create_user(async_test_db_session, role=DVTDefaultRoles.ADMIN.value)
    resolver = _build_ownership_resolver(async_test_db_session)
    existing = _build_connection_record(
        organization_id=admin_actor.organization_id,
        user_id=admin_actor.id,
    )

    resolved = await resolver.resolve_patch(
        SimpleNamespace(actor=admin_actor, operation="update", connection_id=existing.id),
        existing,
        ConnectionPatch(extra={"scope": "archived"}),
    )

    assert resolved.extra == {
        "organization_id": admin_actor.organization_id,
        "user_id": admin_actor.id,
        "scope": "archived",
    }


@pytest.mark.asyncio
async def test_ownership_resolver_patch_uses_existing_org_for_partial_admin_owner_override(
    async_test_db_session,
) -> None:
    admin_actor = await _create_user(async_test_db_session, role=DVTDefaultRoles.ADMIN.value)
    resolver = _build_ownership_resolver(async_test_db_session)
    same_org_user = await _create_user_in_organization(
        async_test_db_session,
        role=DVTDefaultRoles.USER.value,
        organization_id=admin_actor.organization_id,
        email_prefix="patch-org",
    )
    existing = _build_connection_record(
        organization_id=admin_actor.organization_id,
        user_id=admin_actor.id,
    )

    resolved = await resolver.resolve_patch(
        SimpleNamespace(actor=admin_actor, operation="update", connection_id=existing.id),
        existing,
        ConnectionPatch(extra={"user_id": same_org_user.id, "scope": "archived"}),
    )

    assert resolved.extra == {
        "organization_id": admin_actor.organization_id,
        "user_id": same_org_user.id,
        "scope": "archived",
    }


@pytest.mark.asyncio
async def test_repository_crud_and_filters_round_trip(async_test_db_session) -> None:
    actor = await _create_user(async_test_db_session, role=DVTDefaultRoles.ADMIN.value)
    repository = build_db_connection_repository(async_test_db_session, Fernet.generate_key())

    created = await repository.create(
        _build_draft(
            organization_id=actor.organization_id,
            user_id=actor.id,
        )
    )

    assert created.extra["organization_id"] == actor.organization_id
    assert created.extra["user_id"] == actor.id
    assert created.extra["scope"] == "shared"

    filtered = await repository.list(
        ConnectionListQuery(
            extra_filters={
                "organization_id": actor.organization_id,
                "user_id": actor.id,
                "scope": "shared",
            },
            label_filters={"env": "test"},
            metadata_filters={"team": "data"},
        )
    )
    assert [row.id for row in filtered] == [created.id]

    fetched = await repository.get(created.id)
    assert fetched is not None
    assert fetched.id == created.id

    updated = await repository.replace(
        created.id,
        _build_draft(
            organization_id=actor.organization_id,
            user_id=actor.id,
            scope="archived",
        ),
    )
    assert updated is not None
    assert updated.extra["scope"] == "archived"

    deleted = await repository.delete(created.id)
    assert deleted is not None
    assert deleted.deleted_at is not None
    assert await repository.list(ConnectionListQuery()) == []
    assert [row.id for row in await repository.list(ConnectionListQuery(include_deleted=True))] == [
        created.id
    ]


@pytest.mark.asyncio
async def test_repository_requires_owner_fields(async_test_db_session) -> None:
    repository = build_db_connection_repository(async_test_db_session, Fernet.generate_key())
    draft = ConnectionDraft(
        name="Broken owner",
        kind="file",
        type="smbprotocol",
        driver=None,
        driver_options=None,
        properties={"host": "fileserver", "port": 445, "share": "shared", "username": "reader"},
        secrets={"password": "secret"},
        labels={},
        metadata={},
        extra={},
    )

    with pytest.raises(ValidationFailedError):
        await repository.create(draft)


@pytest.mark.asyncio
async def test_repository_preserves_driver_options(async_test_db_session) -> None:
    actor = await _create_user(async_test_db_session, role=DVTDefaultRoles.ADMIN.value)
    repository = build_db_connection_repository(async_test_db_session, Fernet.generate_key())

    created = await repository.create(
        ConnectionDraft(
            name="MSSQL",
            kind="sql",
            type="mssql",
            driver="pyodbc",
            driver_options=ODBCDriverOptions(driver_name="ODBC Driver 18 for SQL Server"),
            properties={
                "host": "localhost",
                "port": 1433,
                "username": "sa",
                "database": "master",
            },
            secrets={"password": "secret"},
            labels={},
            metadata={},
            extra={
                "organization_id": actor.organization_id,
                "user_id": actor.id,
            },
        )
    )

    fetched = await repository.get(created.id)
    listed = await repository.list(ConnectionListQuery(type="mssql"))

    assert created.driver_options == ODBCDriverOptions(driver_name="ODBC Driver 18 for SQL Server")
    assert fetched is not None
    assert fetched.driver_options == created.driver_options
    assert [record.driver_options for record in listed] == [created.driver_options]


def test_smb_protocol_client_builds_unc_paths_and_proxies_calls(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        smbprotocol_client_module.smbclient,
        "register_session",
        lambda *args, **kwargs: calls.append(("register_session", (args, kwargs))),
    )
    monkeypatch.setattr(
        smbprotocol_client_module.smbclient,
        "listdir",
        lambda path, **kwargs: calls.append(("listdir", (path, kwargs))) or ["a.txt"],
    )
    monkeypatch.setattr(
        smbprotocol_client_module.smbclient,
        "delete_session",
        lambda *args, **kwargs: calls.append(("delete_session", (args, kwargs))),
    )

    client = SMBProtocolClient(
        host="fileserver",
        share="shared",
        username="reader",
        password="secret",
    )

    assert client.build_unc_path(path="nested/folder", filename="a.txt") == (
        "\\\\fileserver\\shared\\nested\\folder\\a.txt"
    )
    assert client.listdir("nested/folder") == ["a.txt"]
    client.close()

    assert [name for name, _ in calls] == ["register_session", "listdir", "delete_session"]
    assert calls[1][1][0] == "\\\\fileserver\\shared\\nested\\folder"
    assert calls[1][1][1]["port"] == 445


@pytest.mark.asyncio
async def test_smb_protocol_connector_reports_authentication_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        smbprotocol_client_module.smbclient,
        "register_session",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        smbprotocol_client_module.smbclient,
        "listdir",
        lambda path, **kwargs: (_ for _ in ()).throw(smbprotocol_connector_module.SMBAuthenticationError("bad creds")),
    )
    monkeypatch.setattr(
        smbprotocol_client_module.smbclient,
        "delete_session",
        lambda *args, **kwargs: None,
    )

    result = await SMBProtocolConnector().check(_build_validated_connection())

    assert result.connected is False
    assert result.message == "SMB authentication failed."


@pytest.mark.asyncio
async def test_resolve_connection_client_use_case_returns_generic_client_envelope() -> None:
    client = sa.create_engine("sqlite://")
    connector = _DummyConnector(client)
    registry = _build_dummy_registry(connector)
    service = _ServiceStub(
        record=_build_connection_record(
            organization_id="org-1",
            user_id="user-1",
            connection_type="dummy_sql",
            kind="sql",
            properties={"dsn": "sqlite://"},
            secrets={"token": "secret"},
        )
    )
    use_case = ResolveConnectionClientUseCase(service=service, registry=registry)

    try:
        resolved = await use_case.execute(
            connection_id="conn-1",
            actor=_build_actor(role=DVTDefaultRoles.ADMIN.value, organization_id="org-1", user_id="user-1"),
        )
    finally:
        client.dispose()

    assert resolved.client is client
    assert resolved.connection.id == "conn-1"
    assert resolved.type == "dummy_sql"
    assert resolved.kind == "sql"
    assert resolved.driver is None
    assert connector.received is not None
    assert connector.received.properties.dsn == "sqlite://"


@pytest.mark.asyncio
async def test_resolve_connection_client_use_case_returns_smb_client() -> None:
    registry = build_registry()
    service = _ServiceStub(
        record=_build_connection_record(
            organization_id="org-1",
            user_id="user-1",
        )
    )
    use_case = ResolveConnectionClientUseCase(service=service, registry=registry)

    resolved = await use_case.execute(
        connection_id="conn-1",
        actor=_build_actor(role=DVTDefaultRoles.ADMIN.value, organization_id="org-1", user_id="user-1"),
    )

    assert isinstance(resolved.client, SMBProtocolClient)
    assert resolved.kind == "file"
    assert resolved.type == "smbprotocol"
    await resolved.aclose()


@pytest.mark.asyncio
async def test_resolve_connection_client_use_case_normalizes_record_like_connection() -> None:
    client = sa.create_engine("sqlite://")
    connector = _DummyConnector(client)
    registry = _build_dummy_registry(connector)
    service = _ServiceStub(
        record=SimpleNamespace(
            id="conn-1",
            name="Dummy SQL",
            kind="sql",
            type="dummy_sql",
            driver=None,
            driver_options=None,
            properties={"dsn": "sqlite://"},
            secrets={"token": "secret"},
        )
    )
    use_case = ResolveConnectionClientUseCase(service=service, registry=registry)

    try:
        resolved = await use_case.execute(
            connection_id="conn-1",
            actor=_build_actor(role=DVTDefaultRoles.ADMIN.value, organization_id="org-1", user_id="user-1"),
        )
    finally:
        client.dispose()

    assert resolved.connection.id == "conn-1"
    assert connector.received is not None
    assert connector.received.labels == {}
    assert connector.received.metadata == {}
    assert connector.received.extra == {}


@pytest.mark.asyncio
async def test_resolve_connection_client_use_case_rejects_types_without_client_capability() -> None:
    connector = _DummyConnector(object())
    registry = _build_dummy_registry(connector, capabilities={"check"})
    service = _ServiceStub(
        record=_build_connection_record(
            organization_id="org-1",
            user_id="user-1",
            connection_type="dummy_sql",
            kind="sql",
            properties={"dsn": "sqlite://"},
            secrets={"token": "secret"},
        )
    )
    use_case = ResolveConnectionClientUseCase(service=service, registry=registry)

    with pytest.raises(ValidationFailedError, match="does not support runtime client resolution"):
        await use_case.execute(
            connection_id="conn-1",
            actor=_build_actor(role=DVTDefaultRoles.ADMIN.value, organization_id="org-1", user_id="user-1"),
        )


@pytest.mark.asyncio
async def test_resolved_connection_client_aclose_supports_sync_and_async_closers() -> None:
    sync_state = {"closed": False}
    async_state = {"closed": False}

    class _SyncClient:
        def close(self) -> None:
            sync_state["closed"] = True

    class _AsyncClient:
        async def aclose(self) -> None:
            async_state["closed"] = True

    connection_record = _build_connection_record(organization_id="org-1", user_id="user-1")
    await ResolvedConnectionClient(
        client=_SyncClient(),
        connection=connection_record,
        type="dummy",
        kind="sql",
        driver=None,
    ).aclose()
    await ResolvedConnectionClient(
        client=_AsyncClient(),
        connection=connection_record,
        type="dummy",
        kind="sql",
        driver=None,
    ).aclose()

    assert sync_state["closed"] is True
    assert async_state["closed"] is True


@pytest.mark.asyncio
async def test_build_extension_accepts_external_actor_dependency(async_test_db_engine) -> None:
    extension = build_db_connection_extension(
        engine=async_test_db_engine,
        fernet_key=Fernet.generate_key(),
        get_actor_dependency=lambda: None,
        user_repository_factory=SQLAlchemyUserRepository
    )

    assert extension.get_actor is not None


@pytest.mark.asyncio
async def test_build_resolve_connection_client_use_case_returns_wired_instance(async_test_db_engine) -> None:
    use_case = build_resolve_connection_client_use_case(
        engine=async_test_db_engine,
        fernet_key=Fernet.generate_key(),
        user_repository_factory=SQLAlchemyUserRepository
    )

    assert isinstance(use_case, ResolveConnectionClientUseCase)












