from collections.abc import AsyncGenerator, Generator
from typing import Any

import boto3
import pytest
import pytest_asyncio
from botocore.exceptions import ClientError
from db_connection.application import ConnectionService
from db_connection.connectors.sql import SQLProperties, SQLSecrets
from db_connection.domain import ConnectionDraft, ConnectionRecord
from db_connection.registry.defaults import S3Secrets
from sqlmodel import Session

from src.modules.user.infra.db_models import UserRecord
from src.modules.db_connection.facade import (
    build_connection_service,
)
from src.modules.user.infra.repositories import SQLAlchemyUserRepository

import config

from .containers import (
    clickhouse_container,  # noqa: F401
    # kafka_container,     # noqa: F401
    minio_container,  # noqa: F401
    mongodb_container,  # noqa: F401
    mssql_container,  # noqa: F401
    mysql_container,  # noqa: F401
    oracle_container,  # noqa: F401
    postgres_container,  # noqa: F401
)
from .db import test_db_session  # noqa: F401
from .user import test_admin_user  # noqa: F401


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
        return None

    def in_transaction(self):
        return self._session.in_transaction()


class _ConnectionSessionFactory:
    def __init__(self, session: Session):
        self._session = session

    def __call__(self) -> _AsyncSessionAdapter:
        return _AsyncSessionAdapter(self._session)


@pytest.fixture(scope="function")
def connection_service(test_db_async_engine, test_db_session: Session) -> Generator[ConnectionService]:
    service = build_connection_service(
        engine=test_db_async_engine,
        fernet_key=config.SECURITY.FERNET_KEY,
        user_repository_factory=SQLAlchemyUserRepository
    )
    session_factory = _ConnectionSessionFactory(test_db_session)
    service._uow_factory._session_factory = session_factory
    service._ownership_resolver._user_repository._session_factory = session_factory
    yield service


async def _create_persisted_connection(
    *,
    user: UserRecord,
    connection_service: ConnectionService,
    name: str,
    kind: str,
    connection_type: str,
    properties: dict[str, Any],
    secrets: dict[str, Any],
    driver: str | None = None,
    driver_options: dict[str, Any] | None = None,
) -> ConnectionRecord:
    return await connection_service.create(
        ConnectionDraft(
            name=name,
            kind=kind,
            type=connection_type,
            driver=driver,
            driver_options=driver_options,
            properties=properties,
            secrets=secrets,
            extra={
                "user_id": user.id,
                "organization_id": user.organization_id,
            },
        ),
        actor=user,
    )


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def postgres_db_connection(
    postgres_container, test_admin_user, connection_service
) -> AsyncGenerator[ConnectionRecord]:
    yield await _create_persisted_connection(
        user=test_admin_user,
        connection_service=connection_service,
        name="postgres_test_connection",
        kind="sql",
        connection_type="postgres",
        driver="psycopg",
        properties=SQLProperties(
            host=postgres_container.get_container_host_ip(),
            port=postgres_container.get_exposed_port(5432),
            username=postgres_container.username,
            database=postgres_container.dbname,
        ).model_dump(),
        secrets=SQLSecrets(
            password=postgres_container.password,
        ).model_dump(),
    )


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def clickhouse_db_connection(
    clickhouse_container, test_admin_user, connection_service
) -> AsyncGenerator[ConnectionRecord]:
    yield await _create_persisted_connection(
        user=test_admin_user,
        connection_service=connection_service,
        name="clickhouse_test_connection",
        kind="sql",
        connection_type="clickhouse",
        driver="http",
        properties=SQLProperties(
            host=clickhouse_container.get_container_host_ip(),
            port=clickhouse_container.get_exposed_port(8123),
            username=clickhouse_container.username,
            database=clickhouse_container.dbname,
        ).model_dump(),
        secrets=SQLSecrets(
            password=clickhouse_container.password,
        ).model_dump(),
    )


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def mysql_db_connection(
    mysql_container, test_admin_user, connection_service
) -> AsyncGenerator[ConnectionRecord]:
    yield await _create_persisted_connection(
        user=test_admin_user,
        connection_service=connection_service,
        name="mysql_test_connection",
        kind="sql",
        connection_type="mysql",
        driver="pymysql",
        properties=SQLProperties(
            host=mysql_container.get_container_host_ip(),
            port=mysql_container.get_exposed_port(3306),
            username=mysql_container.username,
            database=mysql_container.dbname,
        ).model_dump(),
        secrets=SQLSecrets(
            password=mysql_container.password,
        ).model_dump(),
    )


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def mongodb_db_connection(
    mongodb_container, test_admin_user, connection_service
) -> AsyncGenerator[ConnectionRecord]:
    yield await _create_persisted_connection(
        user=test_admin_user,
        connection_service=connection_service,
        name="mongodb_test_connection",
        kind="sql",
        connection_type="mongodb",
        properties=SQLProperties(
            host=mongodb_container.get_container_host_ip(),
            port=mongodb_container.get_exposed_port(27017),
            username=mongodb_container.username,
            database=mongodb_container.dbname,
        ).model_dump(),
        secrets=SQLSecrets(
            password=mongodb_container.password,
        ).model_dump(),
    )


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def mssql_db_connection(
    mssql_container, test_admin_user, connection_service
) -> AsyncGenerator[ConnectionRecord]:
    yield await _create_persisted_connection(
        user=test_admin_user,
        connection_service=connection_service,
        name="mssql_test_connection",
        kind="sql",
        connection_type="mssql",
        driver="pyodbc",
        driver_options={"driver_name": "ODBC Driver 18 for SQL Server"},
        properties=SQLProperties(
            host=mssql_container.get_container_host_ip(),
            port=mssql_container.get_exposed_port(1433),
            username=mssql_container.username,
            database=mssql_container.dbname,
        ).model_dump(),
        secrets=SQLSecrets(
            password=mssql_container.password,
        ).model_dump(),
    )


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def s3_db_connection(
    minio_container, test_admin_user, connection_service
) -> AsyncGenerator[ConnectionRecord]:
    endpoint_url = (
        f"http://{minio_container.get_container_host_ip()}:{minio_container.get_exposed_port(9000)}"
    )
    bucket_name = "test-bucket"
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=minio_container.access_key,
        aws_secret_access_key=minio_container.secret_key,
        use_ssl=False,
    )
    try:
        client.create_bucket(Bucket=bucket_name)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code"))
        if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
            raise
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    yield await _create_persisted_connection(
        user=test_admin_user,
        connection_service=connection_service,
        name="s3_test_connection",
        kind="file",
        connection_type="s3",
        properties={
            "bucket": bucket_name,
            "region_name": "us-east-1",
            "endpoint_url": endpoint_url,
            "use_ssl": False,
            "path_style": True,
            "prefix": "integration-tests",
        },
        secrets=S3Secrets(
            access_token_id=minio_container.access_key,
            access_token_key=minio_container.secret_key,
        ).model_dump(),
    )


@pytest.fixture(scope="function")
def get_mock_s3_db_connection(s3_db_connection) -> Generator[ConnectionRecord, Any]:
    yield s3_db_connection


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def oracle_db_connection(
    oracle_container, test_admin_user, connection_service
) -> AsyncGenerator[ConnectionRecord]:
    username = oracle_container.username or "system"
    password = oracle_container.password or oracle_container.oracle_password
    database = oracle_container.dbname or "FREEPDB1"
    yield await _create_persisted_connection(
        user=test_admin_user,
        connection_service=connection_service,
        name="oracle_test_connection",
        kind="sql",
        connection_type="oracle",
        driver="oracledb",
        properties=SQLProperties(
            host=oracle_container.get_container_host_ip(),
            port=oracle_container.get_exposed_port(1521),
            username=username,
            database=database,
        ).model_dump(),
        secrets=SQLSecrets(
            password=password,
        ).model_dump(),
    )
