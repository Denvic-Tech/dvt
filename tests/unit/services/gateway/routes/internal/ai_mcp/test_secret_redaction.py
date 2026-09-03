from services.gateway.routes.internal.ai_mcp.access import sanitized_mapping


def test_connection_payload_redacts_secret_keys_and_credential_urls() -> None:
    sanitized = sanitized_mapping(
        {
            "host": "db.internal",
            "password": "secret-value",
            "endpoint": "postgresql://user:password@db.internal/database",
            "nested": {"presigned_url": "https://storage/file?signature=secret"},
        }
    )

    assert sanitized == {
        "host": "db.internal",
        "endpoint": "<redacted-credential-url>",
        "nested": {},
    }
