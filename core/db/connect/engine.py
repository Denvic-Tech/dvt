from typing import Any, Callable

import sqlalchemy as sa

from .sqlalchemy_url import split_backend_and_driver, with_database


def _apply_connect_timeout_to_url(
    *,
    connection_url: sa.URL,
    connect_timeout_sec: int | None,
) -> sa.URL:
    if connect_timeout_sec is None:
        return connection_url

    backend_name, driver_name = split_backend_and_driver(connection_url)
    if backend_name != "clickhouse":
        return connection_url

    query = dict(connection_url.query)
    if driver_name in {None, "http"}:
        query["timeout"] = str(connect_timeout_sec)
    else:
        query["connect_timeout"] = str(connect_timeout_sec)
        query["send_receive_timeout"] = str(connect_timeout_sec)
    return connection_url.set(query=query)


def _build_connect_args(
    *,
    connection_url: sa.URL,
    connect_timeout_sec: int | None,
) -> dict[str, Any]:
    if connect_timeout_sec is None:
        return {}

    dialect_name = connection_url.get_backend_name()
    if dialect_name in {"postgresql", "mysql", "mariadb"}:
        return {"connect_timeout": connect_timeout_sec}
    if dialect_name == "mssql":
        return {"timeout": connect_timeout_sec}

    return {}


def build_engine_from_connection_string(
    *,
    connection_string: str,
    database_name: str | None = None,
    decrypt_url_fn: Callable[[sa.URL], sa.URL] | None = None,
    connect_timeout_sec: int | None = None,
) -> sa.Engine:
    connection_url = sa.make_url(connection_string)

    if decrypt_url_fn is not None:
        connection_url = decrypt_url_fn(connection_url)

    connection_url = with_database(connection_url, database_name)
    connection_url = _apply_connect_timeout_to_url(
        connection_url=connection_url,
        connect_timeout_sec=connect_timeout_sec,
    )
    connect_args = _build_connect_args(
        connection_url=connection_url,
        connect_timeout_sec=connect_timeout_sec,
    )

    return sa.create_engine(url=connection_url, connect_args=connect_args)
