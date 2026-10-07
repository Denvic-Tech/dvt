from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from core.security import derive_legacy_auth_secret

from services.installation_manager.domain import services as domain

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location(
    "offline_config",
    ROOT / "scripts/offline/offline-config.py",
)
offline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(offline)


def test_fresh_install_generates_identity_and_distinct_secrets(tmp_path):
    cfg = offline.prepare_configuration(
        tmp_path,
        mode="install",
        version="1.22.0",
        host_dir="/var/lib/dvt",
        public_url="https://dvt.example",
        ai_mcp=True,
        workers=3,
    )
    values = domain.parse_env_file((tmp_path / ".env").read_text(encoding="utf-8"))
    secrets = [values[name] for _, name in domain.AUTH_SECRET_FIELDS]
    assert len(set(secrets)) == len(secrets)
    assert all(len(secret) >= 32 for secret in secrets)
    assert values["DVT_COOKIE_SECURE"] == "true"
    assert values["COMPOSE_PROFILES"] == "ai-mcp"
    assert len(values["DVT_AI_MCP_INTERNAL_SECRET"]) >= 32
    assert cfg.task_workers_count == 3
    assert (tmp_path / "installation/instance_id").read_text().strip()
    assert (tmp_path / "data/valkeydata").is_dir()


def test_update_keeps_data_identity_settings_and_legacy_signing_secrets(tmp_path):
    fernet = domain.generate_fernet_key()
    content = (
        "# customer configuration\nCOMPOSE_PROJECT_NAME=customer-dvt\n"
        "DVT_VERSION=1.21.0\nDVT_POSTGRES_PASSWORD=existing-db-password\n"
        f"DVT_FERNET_KEY={fernet}\nDVT_VALKEY_PASSWORD=existing-valkey-password\n"
        "DVT_PUBLIC_URL=https://customer.example\nDVT_TASK_WORKERS_COUNT=4\n"
        "COMPOSE_PROFILES=metrics\nCUSTOM_SETTING=keep-me\n"
    )
    (tmp_path / ".env").write_text(content, encoding="utf-8")
    (tmp_path / "installation").mkdir()
    identity = tmp_path / "installation/instance_id"
    identity.write_text("existing-instance\n")
    (tmp_path / "data").mkdir()
    marker = tmp_path / "data/customer-data"
    marker.write_bytes(b"persisted")
    cfg = offline.prepare_configuration(
        tmp_path,
        mode="update",
        version="1.22.0",
        host_dir="/customer/dvt",
    )
    after = (tmp_path / ".env").read_text(encoding="utf-8")
    values = domain.parse_env_file(after)
    assert values["DVT_VERSION"] == "1.22.0"
    assert values["DVT_LIB_DIR"] == "/customer/dvt"
    assert values["CUSTOM_SETTING"] == "keep-me"
    assert values["COMPOSE_PROFILES"] == "metrics"
    assert values["DVT_POSTGRES_PASSWORD"] == "existing-db-password"
    assert values["DVT_VALKEY_PASSWORD"] == "existing-valkey-password"
    assert values["DVT_FERNET_KEY"] == fernet
    assert cfg.task_workers_count == 4
    assert identity.read_text() == "existing-instance\n"
    assert marker.read_bytes() == b"persisted"
    assert next(tmp_path.glob(".env.bak.*")).read_text(encoding="utf-8") == content
    for _, name in domain.AUTH_SECRET_FIELDS:
        assert values[name] == derive_legacy_auth_secret(fernet, name.removeprefix("DVT_"))


def test_repeat_install_does_not_rotate_persisted_keys(tmp_path):
    offline.prepare_configuration(tmp_path, mode="install", version="1.22.0", host_dir="/dvt")
    before = domain.parse_env_file((tmp_path / ".env").read_text(encoding="utf-8"))
    identity = (tmp_path / "installation/instance_id").read_text()
    offline.prepare_configuration(tmp_path, mode="install", version="1.23.0", host_dir="/dvt")
    after = domain.parse_env_file((tmp_path / ".env").read_text(encoding="utf-8"))
    for _, name in domain.AUTH_SECRET_FIELDS:
        assert after[name] == before[name]
    assert after["DVT_FERNET_KEY"] == before["DVT_FERNET_KEY"]
    assert (tmp_path / "installation/instance_id").read_text() == identity


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "update"},
        {"workers": 0},
        {"external_port": "65536"},
        {"public_url": "https://example\nINJECTED=value"},
    ],
)
def test_invalid_configuration_does_not_write_files(tmp_path, changes):
    arguments = {"mode": "install", "version": "1.22.0", "host_dir": "/dvt"}
    arguments.update(changes)
    with pytest.raises(ValueError):
        offline.prepare_configuration(tmp_path, **arguments)
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "installation").exists()
