from typing import Generator, Any

import pytest

from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer
from testcontainers.clickhouse import ClickHouseContainer
from testcontainers.mysql import MySqlContainer
from testcontainers.mongodb import MongoDbContainer
from testcontainers.mssql import SqlServerContainer
from testcontainers.kafka import KafkaContainer
from testcontainers.minio import MinioContainer
from testcontainers.oracle import OracleDbContainer


CONTAINERS_TIMEOUT = 300


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, Any, None]:
    """
    Postgres test container
    """
    with PostgresContainer(
            "postgres:15.3-alpine",
            driver="psycopg",
            docker_client_kw={"timeout": CONTAINERS_TIMEOUT}
    ) as postgres:
        yield postgres


@pytest.fixture(scope="session")
def redis_container() -> Generator[RedisContainer, Any, None]:
    """
    Redis test container
    """
    with RedisContainer(
            "redis:8.4-alpine",
            docker_client_kw={"timeout": CONTAINERS_TIMEOUT}
    ) as redis:
        yield redis


@pytest.fixture(scope="session")
def clickhouse_container() -> Generator[ClickHouseContainer, Any, None]:
    """
    ClickHouse test container
    """
    with ClickHouseContainer(
            "clickhouse/clickhouse-server:24.11",
            docker_client_kw={"timeout": CONTAINERS_TIMEOUT}
    ) as clickhouse:
        yield clickhouse


@pytest.fixture(scope="session")
def mysql_container() -> Generator[MySqlContainer, Any, None]:
    """
    MySQL test container
    """
    with MySqlContainer(
            "mysql:8.0",
            dialect="pymysql",
            docker_client_kw={"timeout": CONTAINERS_TIMEOUT}
    ) as mysql:
        yield mysql


@pytest.fixture(scope="session")
def mongodb_container() -> Generator[MongoDbContainer, Any, None]:
    """
    MongoDB test container
    """
    with MongoDbContainer(
            "mongo:7.0.7",
            docker_client_kw={"timeout": CONTAINERS_TIMEOUT}
    ) as mongo:
        yield mongo


@pytest.fixture(scope="session")
def mssql_container() -> Generator[SqlServerContainer, Any, None]:
    """
    MSSQL test container
    """
    with SqlServerContainer(
            "mcr.microsoft.com/mssql/server:2022-CU12-ubuntu-22.04",
            dialect="mssql+pyodbc",
            docker_client_kw={"timeout": CONTAINERS_TIMEOUT}
    ) as mssql:
        yield mssql


@pytest.fixture(scope="session")
def kafka_container() -> Generator[KafkaContainer, Any, None]:
    """
    Kafka test container
    """
    with KafkaContainer(
            "confluentinc/cp-kafka:7.6.0",
            docker_client_kw={"timeout": CONTAINERS_TIMEOUT}
    ) as kafka:
        yield kafka


@pytest.fixture(scope="session")
def minio_container() -> Generator[MinioContainer, Any, None]:
    """
    MinIO test container (S3 compatible)
    """
    with MinioContainer(
            "minio/minio:RELEASE.2024-08-17T01-24-54Z",
            docker_client_kw={"timeout": CONTAINERS_TIMEOUT}
    ) as minio:
        yield minio


@pytest.fixture(scope="session")
def oracle_container() -> Generator[OracleDbContainer, Any, None]:
    """
    Oracle test container
    """
    with OracleDbContainer(
            "gvenzl/oracle-free:23-slim-faststart",
            docker_client_kw={"timeout": CONTAINERS_TIMEOUT}
    ) as oracle:
        yield oracle
