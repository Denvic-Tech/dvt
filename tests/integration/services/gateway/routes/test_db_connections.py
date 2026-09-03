from __future__ import annotations

from importlib.util import find_spec
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.docker_required]


ALL_CONTAINER_DB_TYPES = [
    pytest.param("postgres", id="postgres"),
    pytest.param("clickhouse", id="clickhouse"),
    pytest.param("mysql", id="mysql"),
    pytest.param("mongodb", id="mongodb"),
    pytest.param("mssql", id="mssql"),
    # pytest.param("kafka", id="kafka"),
    pytest.param("s3", id="s3"),
    pytest.param("oracle", id="oracle"),
]


@pytest.fixture(autouse=True)
def _patch_sqlalchemy_session_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlalchemy.orm

    def _exec(session, statement, *args, **kwargs):
        return session.execute(statement, *args, **kwargs).scalars()

    monkeypatch.setattr(sqlalchemy.orm.Session, "exec", _exec, raising=False)


def _skip_if_driver_missing(db_type: str) -> None:
    if db_type == "mssql" and find_spec("pyodbc") is None:
        pytest.skip("pyodbc is not installed; MSSQL integration tests are skipped")

    if db_type == "oracle" and find_spec("oracledb") is None:
        pytest.skip("oracledb is not installed; Oracle integration tests are skipped")


def _ensure_minio_bucket(request: pytest.FixtureRequest, bucket_name: str) -> None:
    import boto3
    from botocore.exceptions import ClientError

    minio_container = request.getfixturevalue("minio_container")
    endpoint_url = (
        f"http://{minio_container.get_container_host_ip()}:"
        f"{minio_container.get_exposed_port(9000)}"
    )
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


def _build_payload_for_db_type(db_type: str, request: pytest.FixtureRequest) -> dict:
    name = f"it-db-conn-{db_type}-{uuid4().hex[:8]}"

    if db_type == "postgres":
        container = request.getfixturevalue("postgres_container")
        return {
            "name": name,
            "kind": "sql",
            "type": "postgres",
            "driver": "psycopg",
            "properties": {
                "host": container.get_container_host_ip(),
                "port": int(container.get_exposed_port(5432)),
                "username": container.username,
                "database": container.dbname,
            },
            "secrets": {
                "password": container.password,
            },
        }

    if db_type == "clickhouse":
        container = request.getfixturevalue("clickhouse_container")
        return {
            "name": name,
            "kind": "sql",
            "type": "clickhouse",
            "driver": "native",
            "properties": {
                "host": container.get_container_host_ip(),
                "port": int(container.get_exposed_port(8123)),
                "username": container.username,
                "database": container.dbname,
            },
            "secrets": {
                "password": container.password,
            },
        }

    if db_type == "mysql":
        container = request.getfixturevalue("mysql_container")
        return {
            "name": name,
            "kind": "sql",
            "type": "mysql",
            "driver": "pymysql",
            "properties": {
                "host": container.get_container_host_ip(),
                "port": int(container.get_exposed_port(3306)),
                "username": container.username,
                "database": container.dbname,
            },
            "secrets": {
                "password": container.password,
            },
        }

    if db_type == "mongodb":
        container = request.getfixturevalue("mongodb_container")
        return {
            "name": name,
            "kind": "sql",
            "type": "mongodb",
            "properties": {
                "host": container.get_container_host_ip(),
                "port": int(container.get_exposed_port(27017)),
                "username": container.username,
                "database": container.dbname,
            },
            "secrets": {
                "password": container.password,
            },
        }

    if db_type == "mssql":
        container = request.getfixturevalue("mssql_container")
        return {
            "name": name,
            "kind": "sql",
            "type": "mssql",
            "driver": "pyodbc",
            "driver_options": {
                "driver_name": "ODBC Driver 18 for SQL Server",
            },
            "properties": {
                "host": container.get_container_host_ip(),
                "port": int(container.get_exposed_port(1433)),
                "username": container.username,
                "database": container.dbname,
            },
            "secrets": {
                "password": container.password,
            },
        }

    if db_type == "kafka":
        container = request.getfixturevalue("kafka_container")
        return {
            "name": name,
            "type": "kafka",
            "connection_properties": {
                "bootstrap_servers": [container.get_bootstrap_server()],
            },
        }

    if db_type == "s3":
        container = request.getfixturevalue("minio_container")
        bucket_name = "test-bucket"
        _ensure_minio_bucket(request=request, bucket_name=bucket_name)
        endpoint_url = (
            f"http://{container.get_container_host_ip()}:"
            f"{container.get_exposed_port(9000)}"
        )
        return {
            "name": name,
            "kind": "file",
            "type": "s3",
            "properties": {
                "bucket": bucket_name,
                "region_name": "us-east-1",
                "endpoint_url": endpoint_url,
                "use_ssl": False,
                "path_style": True,
                "prefix": "integration-tests",
            },
            "secrets": {
                "access_token_id": container.access_key,
                "access_token_key": container.secret_key,
            },
        }

    if db_type == "oracle":
        container = request.getfixturevalue("oracle_container")
        username = container.username or "system"
        password = container.password or container.oracle_password
        database = container.dbname or "FREEPDB1"
        return {
            "name": name,
            "kind": "sql",
            "type": "oracle",
            "driver": "oracledb",
            "properties": {
                "host": container.get_container_host_ip(),
                "port": int(container.get_exposed_port(1521)),
                "username": username,
                "database": database,
            },
            "secrets": {
                "password": password,
            },
        }

    raise ValueError(f"Unsupported db_type for tests: {db_type}")


@pytest.mark.parametrize("db_type", ALL_CONTAINER_DB_TYPES)
async def test_db_connections_routes_crud_and_check_for_all_container_types(
    db_type: str,
    gateway_client,
    router_prefix: str,
    request: pytest.FixtureRequest,
) -> None:
    _skip_if_driver_missing(db_type)
    payload = _build_payload_for_db_type(db_type=db_type, request=request)

    create_response = await gateway_client.post(
        f"{router_prefix}/db-connections",
        json=payload,
    )
    assert create_response.status_code == 200, create_response.text
    created = create_response.json()
    assert created["id"]
    assert created["name"] == payload["name"]
    assert created["kind"] == payload["kind"]
    assert created["type"] == payload["type"]

    connection_id = created["id"]

    list_response = await gateway_client.get(
        f"{router_prefix}/db-connections",
        params={"type": payload["type"]},
    )
    assert list_response.status_code == 200
    listed = list_response.json()
    assert any(item["id"] == connection_id for item in listed)

    get_response = await gateway_client.get(f"{router_prefix}/db-connections/{connection_id}")
    assert get_response.status_code == 200
    read_back = get_response.json()
    assert read_back["id"] == connection_id
    assert read_back["name"] == payload["name"]
    assert read_back["kind"] == payload["kind"]
    assert read_back["type"] == payload["type"]

    check_response = await gateway_client.post(
        f"{router_prefix}/db-connections/check",
        json=payload,
    )
    assert check_response.status_code == 200
    check_status = check_response.json()
    assert check_status["name"] == payload["name"]
    assert isinstance(check_status["connected"], bool)

    check_by_id_response = await gateway_client.post(
        f"{router_prefix}/db-connections/{connection_id}/check",
        json={},
    )
    assert check_by_id_response.status_code == 200
    check_by_id_status = check_by_id_response.json()
    assert check_by_id_status["name"] == payload["name"]
    assert isinstance(check_by_id_status["connected"], bool)

    delete_response = await gateway_client.delete(f"{router_prefix}/db-connections/{connection_id}")
    assert delete_response.status_code == 200
    deleted = delete_response.json()
    assert deleted["id"] == connection_id
    assert deleted["deleted_at"] is not None

    deleted_get_response = await gateway_client.get(f"{router_prefix}/db-connections/{connection_id}")
    assert deleted_get_response.status_code == 404
