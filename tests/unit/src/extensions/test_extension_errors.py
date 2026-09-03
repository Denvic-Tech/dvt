from src.extensions.errors import sanitize_extension_error


def test_extension_error_sanitizer_redacts_named_secrets_in_repr_and_json() -> None:
    message = (
        "request failed: {'password': 'secret-value', 'api_key': 'api-value'}; "
        '{"token": "token value"}'
    )

    sanitized = sanitize_extension_error(message)

    assert "secret-value" not in sanitized
    assert "api-value" not in sanitized
    assert "token value" not in sanitized
    assert sanitized.count("***") >= 3


def test_extension_error_sanitizer_redacts_authorization_and_url_credentials() -> None:
    message = (
        "Authorization: Bearer confidential-token; "
        "postgresql://service-user:db-password@example.invalid/dvt"
    )

    sanitized = sanitize_extension_error(message)

    assert "confidential-token" not in sanitized
    assert "db-password" not in sanitized
    assert "Authorization: ***" in sanitized
    assert "postgresql://service-user:***@" in sanitized
