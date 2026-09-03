from services.gateway.routes.internal.ai_mcp.redaction import redact_log_message


def test_task_log_redaction_masks_common_credential_shapes() -> None:
    message = (
        "Bearer bearer-secret password=hunter2 "
        "postgresql://user:db-password@db.local/events "
        "dvt_mcp_00000000-0000-0000-0000-000000000000." + "a" * 43 + " AKIA1234567890ABCDEF"
    )

    redacted = redact_log_message(message)

    assert "bearer-secret" not in redacted
    assert "hunter2" not in redacted
    assert "db-password" not in redacted
    assert "dvt_mcp_" not in redacted
    assert "AKIA1234567890ABCDEF" not in redacted
