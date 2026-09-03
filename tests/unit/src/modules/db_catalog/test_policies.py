import pytest

from src.modules.db_catalog.domain import (
    AuthorizedCatalogConnection,
    CatalogOperation,
    CatalogRequest,
    CatalogRequestValidationError,
    CatalogUnsupportedError,
)
from src.modules.db_catalog.domain.policies import (
    build_cache_key,
    decode_cursor,
    encode_cursor,
    validate_request,
)


def _connection(dialect="postgresql"):
    return AuthorizedCatalogConnection(
        id="conn",
        revision="revision",
        dialect=dialect,
        configured_database="db",
        connection_url="postgresql://user:secret@host/db",
    )


def test_cursor_roundtrip_and_invalid_cursor():
    cursor = encode_cursor("äbc", "Äbc")
    assert decode_cursor(cursor) == ("äbc", "Äbc")
    with pytest.raises(CatalogRequestValidationError):
        decode_cursor("not-json")


def test_cache_key_does_not_expose_scope_or_secret():
    request = CatalogRequest(
        operation=CatalogOperation.TABLES,
        database_name="sensitive_database",
        schema_name="private_schema",
        search="customer",
    )
    key = build_cache_key(_connection(), request, epoch=1)

    assert "sensitive_database" not in key
    assert "private_schema" not in key
    assert "secret" not in key


def test_request_validation_rejects_unsupported_level_and_large_page():
    with pytest.raises(CatalogUnsupportedError):
        validate_request(
            _connection("sqlite"),
            CatalogRequest(operation=CatalogOperation.DATABASES),
        )
    with pytest.raises(CatalogRequestValidationError):
        validate_request(
            _connection(),
            CatalogRequest(operation=CatalogOperation.TABLES, limit=201),
        )
