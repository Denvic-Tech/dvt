from __future__ import annotations

import pytest
import sqlalchemy as sa

from core.db.connect.clickhouse import ClickHouseHttpInterfaceError, build_clickhouse_client_kwargs
from core.db.read_v3.resolver import resolve_executor

pytestmark = pytest.mark.docker_required


def test_native_connection_on_custom_port_fails_with_http_interface_error(
    clickhouse_container,
) -> None:
    # The container publishes the native port 9000 on a random host port: a custom native port.
    host = clickhouse_container.get_container_host_ip()
    native_port = int(clickhouse_container.get_exposed_port(9000))
    engine = sa.create_engine(
        sa.engine.URL.create(
            "clickhouse+native",
            username=clickhouse_container.username,
            password=clickhouse_container.password,
            host=host,
            port=native_port,
            database=clickhouse_container.dbname,
        )
    )
    try:
        # SQLAlchemy metadata paths work over the native protocol ...
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1").scalar() == 1

        # ... while the clickhouse_connect paths of the V3/V4 nodes cannot use it.
        with pytest.raises(ClickHouseHttpInterfaceError, match="native driver on port") as exc:
            build_clickhouse_client_kwargs(engine)
        assert str(native_port) in str(exc.value)
        assert "driver to http" in str(exc.value)

        with pytest.raises(ClickHouseHttpInterfaceError):
            resolve_executor(engine)
    finally:
        engine.dispose()
