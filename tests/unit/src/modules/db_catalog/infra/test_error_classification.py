import sqlalchemy as sa

from src.modules.db_catalog.domain.exceptions import (
    CatalogSourceTimeoutError,
    CatalogSourceUnavailableError,
    CatalogTableNotFoundError,
)
from src.modules.db_catalog.infra.gateways.sqlalchemy_catalog import (
    _classify_dbapi_error,
    sanitize_driver_message,
)


class _DriverError(Exception):
    pass


class _PostgresError(Exception):
    sqlstate = "3D000"


def _wrap(original: Exception) -> sa.exc.DBAPIError:
    return sa.exc.DBAPIError("select 1", {}, original)


def test_missing_database_is_classified_as_not_found_with_sanitized_detail():
    error = _classify_dbapi_error(
        _wrap(_PostgresError('connection failed: FATAL:  database "DVT_Test" does not exist\nsecond line'))
    )
    assert isinstance(error, CatalogTableNotFoundError)
    assert 'database "DVT_Test" does not exist' in str(error)
    assert "\n" not in str(error)

    mysql = _classify_dbapi_error(_wrap(_DriverError("(1049, \"Unknown database 'analytics'\")")))
    assert isinstance(mysql, CatalogTableNotFoundError)


def test_missing_relation_is_not_a_missing_database():
    error = _classify_dbapi_error(_wrap(_DriverError('relation "orders" does not exist')))
    assert isinstance(error, CatalogSourceUnavailableError)
    assert str(error).endswith('relation "orders" does not exist')


def test_timeouts_and_connection_failures():
    assert isinstance(
        _classify_dbapi_error(_wrap(_DriverError("canceling statement due to statement timeout"))),
        CatalogSourceTimeoutError,
    )
    refused = _classify_dbapi_error(_wrap(_DriverError("could not connect to server: Connection refused")))
    assert isinstance(refused, CatalogSourceUnavailableError)
    assert "Connection refused" in str(refused)


def test_sanitize_driver_message_truncates_and_flattens():
    assert sanitize_driver_message(None) == ""
    assert sanitize_driver_message(_DriverError("a\n  b\tc")) == "a b c"
    assert len(sanitize_driver_message(_DriverError("x" * 1000))) == 300
