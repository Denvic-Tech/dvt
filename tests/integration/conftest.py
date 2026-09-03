import asyncio
import sys

import pytest

from .fixtures.settings import apply_integration_test_env

# psycopg async driver on Windows requires a selector-based event loop.
# Configure it once before importing fixtures or collecting async tests.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

apply_integration_test_env()

from .fixtures.app import (  # noqa: E402
    auth_app,  # noqa: F403
    gateway_app,  # noqa: F403
    gateway_client,  # noqa: F403
    gateway_fixture_context,  # noqa: F403
    gateway_http_client,  # noqa: F403
    router_prefix,  # noqa: F403
    unauthenticated_gateway_client,  # noqa: F403
)
from .fixtures.config import (  # noqa: E402
    app_config,  # noqa: F403
    fernet_key_test,  # noqa: F403
    integration_test_settings,  # noqa: F403
    router_config,  # noqa: F403
)
from .fixtures.containers import (  # noqa: E402
    clickhouse_container,  # noqa: F403
    # kafka_container,  # noqa: F403
    minio_container,  # noqa: F403
    mongodb_container,  # noqa: F403
    mssql_container,  # noqa: F403
    mysql_container,  # noqa: F403
    oracle_container,  # noqa: F403
    postgres_container,  # noqa: F403
    redis_container,  # noqa: F403
)
from .fixtures.db import (  # noqa: E402
    db_session,  # noqa: F403
    test_db_async_engine,  # noqa: F403
    test_db_async_session,  # noqa: F403
    test_db_engine,  # noqa: F403
    test_db_session,  # noqa: F403
    test_db_url,  # noqa: F403
    test_dvt_db_engine,  # noqa: F403
    test_dvt_db_session,  # noqa: F403
)
from .fixtures.db_connection_clients import (  # noqa: E402
    clickhouse_http_test_engine,  # noqa: F403
    mongodb_test_engine,  # noqa: F403
    mssql_test_engine,  # noqa: F403
    mysql_test_engine,  # noqa: F403
    oracle_test_engine,  # noqa: F403
    postgres_test_engine,  # noqa: F403
    # kafka_client,  # noqa: F403
    s3_test_client,  # noqa: F403
)
from .fixtures.db_connections import (  # noqa: E402
    clickhouse_db_connection,  # noqa: F403
    connection_service,  # noqa: F403
    get_mock_s3_db_connection,  # noqa: F403
    mongodb_db_connection,  # noqa: F403
    mssql_db_connection,  # noqa: F403
    mysql_db_connection,  # noqa: F403
    oracle_db_connection,  # noqa: F403
    postgres_db_connection,  # noqa: F403
    # kafka_db_connection,  # noqa: F403
    s3_db_connection,  # noqa: F403
)
from .fixtures.dvt_prod_containers import (  # noqa: E402
    dvt_network,  # noqa: F403
    dvt_postgres_container,  # noqa: F403
    dvt_valkey_container,  # noqa: F403
    gateway_container,  # noqa: F403
    orchestrator_container,  # noqa: F403
    project_scheduler_container,  # noqa: F403
    task_worker_container,  # noqa: F403
)
from .fixtures.gateway_live import (  # noqa: E402
    gateway_auth_headers,  # noqa: F403
    gateway_live_base_url,  # noqa: F403
    gateway_live_client,  # noqa: F403
    gateway_live_unauthenticated_client,  # noqa: F403
    gateway_setup_credentials,  # noqa: F403
)
from .fixtures.project import test_admin_project, test_user_project  # noqa: F403E402
from .fixtures.queue_topic import (  # noqa: E402
    other_queue_topic,  # noqa: F403
    queue_topic_columns,  # noqa: F403
    test_queue_topic,  # noqa: F403
)
from .fixtures.user import (  # noqa: E402
    other_user_email,  # noqa: F403
    other_user_password,  # noqa: F403
    test_admin_user,  # noqa: F403
    test_dvt_admin_user,  # noqa: F403
    test_dvt_organization,  # noqa: F403
    test_dvt_user,  # noqa: F403
    test_organization,  # noqa: F403
    test_user,  # noqa: F403
    test_user_email,  # noqa: F403
    test_user_password,  # noqa: F403
)
