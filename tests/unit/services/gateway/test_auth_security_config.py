import pytest

import config


def _set_valid_auth_secrets(monkeypatch) -> None:
    for index, name in enumerate(config.SECURITY._AUTH_SECRET_NAMES):
        monkeypatch.setattr(config.SECURITY, name, f"secret-{index}-" + "x" * 32)


def test_security_validation_requires_all_auth_secrets_in_prod(monkeypatch) -> None:
    monkeypatch.setattr(config.COMMON, "ENVIRONMENT", "prod")
    _set_valid_auth_secrets(monkeypatch)
    monkeypatch.setattr(config.SECURITY, "JWT_ACCESS_TOKEN_SECRET_KEY", "")

    with pytest.raises(RuntimeError, match="missing: JWT_ACCESS_TOKEN_SECRET_KEY"):
        config.SECURITY.validate()


def test_security_validation_rejects_short_auth_secrets_in_prod(monkeypatch) -> None:
    monkeypatch.setattr(config.COMMON, "ENVIRONMENT", "prod")
    _set_valid_auth_secrets(monkeypatch)
    monkeypatch.setattr(config.SECURITY, "CODE_HASH_SALT", "short")

    with pytest.raises(RuntimeError, match="shorter than 32 characters: CODE_HASH_SALT"):
        config.SECURITY.validate()


def test_security_validation_rejects_reused_auth_secrets_in_prod(monkeypatch) -> None:
    monkeypatch.setattr(config.COMMON, "ENVIRONMENT", "prod")
    _set_valid_auth_secrets(monkeypatch)
    shared = "shared-secret-" + "x" * 32
    monkeypatch.setattr(config.SECURITY, "JWT_ACCESS_TOKEN_SECRET_KEY", shared)
    monkeypatch.setattr(config.SECURITY, "JWT_REFRESH_TOKEN_SECRET_KEY", shared)

    with pytest.raises(RuntimeError, match="must be unique"):
        config.SECURITY.validate()


def test_security_validation_allows_dev_only_defaults(monkeypatch) -> None:
    monkeypatch.setattr(config.COMMON, "ENVIRONMENT", "dev")
    for name in config.SECURITY._AUTH_SECRET_NAMES:
        monkeypatch.setattr(config.SECURITY, name, "")

    config.SECURITY.validate()
