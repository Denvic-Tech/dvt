"""Prepare DVT configuration inside the release's loaded installation_manager image."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from services.installation_manager.domain import services as domain
from services.installation_manager.domain.models import InstallConfig


def prepare_configuration(
    root: Path,
    *,
    mode: str,
    version: str,
    host_dir: str,
    public_url: str | None = None,
    external_port: str | None = None,
    workers: int | None = None,
    ai_mcp: bool | None = None,
) -> InstallConfig:
    env_path = root / ".env"
    content = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
    existing = domain.parse_env_file(content)
    if mode == "update" and not existing:
        raise ValueError("Update requires an existing nonempty .env")
    if mode == "update" and any(
        not existing.get(name) for name in ("DVT_POSTGRES_PASSWORD", "DVT_FERNET_KEY")
    ):
        raise ValueError("Update requires existing PostgreSQL and Fernet secrets")
    cfg = InstallConfig(
        version=version,
        lib_dir_host=host_dir,
        project_name=existing.get("COMPOSE_PROJECT_NAME") or "dvt",
        public_urls=(public_url or existing.get("DVT_PUBLIC_URL") or "http://localhost").split(";"),
        postgres_user=existing.get("DVT_POSTGRES_USER") or "dvt-user",
        postgres_db=existing.get("DVT_POSTGRES_DB") or "DVT",
        postgres_password=existing.get("DVT_POSTGRES_PASSWORD") or domain.generate_password(),
        valkey_password=existing.get("DVT_VALKEY_PASSWORD") or domain.generate_password(),
        valkey_db=existing.get("DVT_VALKEY_DB") or "0",
        grpc_token=existing.get("DVT_GRPC_FORWARD_SERVICE_TOKEN") or domain.generate_password(),
        fernet_key=existing.get("DVT_FERNET_KEY") or domain.generate_fernet_key(),
        ai_mcp_enabled=(
            ai_mcp
            if ai_mcp is not None
            else domain.parse_bool_value(existing.get("DVT_AI_MCP_ENABLED"))
        ),
        ai_mcp_internal_secret=existing.get("DVT_AI_MCP_INTERNAL_SECRET", ""),
        external_port=external_port or existing.get("DVT_EXTERNAL_PORT") or "80",
        task_workers_count=(
            workers if workers is not None else int(existing.get("DVT_TASK_WORKERS_COUNT") or "1")
        ),
    )
    if cfg.task_workers_count < 1 or not 1 <= int(cfg.external_port) <= 65535:
        raise ValueError("Workers must be positive and port must be in 1..65535")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", cfg.project_name):
        raise ValueError("Invalid Compose project name")
    if not domain.is_valid_fernet_key(cfg.fernet_key):
        raise ValueError("Invalid existing Fernet key; refusing to replace it")
    if cfg.ai_mcp_enabled and not cfg.ai_mcp_internal_secret:
        cfg.ai_mcp_internal_secret = domain.generate_password()
    domain.validate_ai_mcp_secret(cfg.ai_mcp_internal_secret, enabled=cfg.ai_mcp_enabled)
    domain.populate_install_auth_secrets(cfg, existing)
    if any(
        "\n" in value or "\r" in value
        for value in [
            *cfg.public_urls,
            *(value for value in vars(cfg).values() if isinstance(value, str)),
        ]
    ):
        raise ValueError("Configuration values must not contain newlines")
    generated = domain.parse_env_file(domain.render_env_file(cfg))
    # Preserve manually added settings, existing passwords, signing keys and profiles.
    values = {key: value for key, value in generated.items() if not existing.get(key)}
    values.update(DVT_VERSION=version, DVT_LIB_DIR=host_dir)
    if public_url is not None:
        values.update(DVT_PUBLIC_URL=cfg.public_url, DVT_COOKIE_SECURE=cfg.cookie_secure)
    if external_port is not None:
        values["DVT_EXTERNAL_PORT"] = cfg.external_port
    if workers is not None:
        values["DVT_TASK_WORKERS_COUNT"] = str(cfg.task_workers_count)
    if ai_mcp is not None:
        values["DVT_AI_MCP_ENABLED"] = domain.render_bool(cfg.ai_mcp_enabled)
    values["COMPOSE_PROFILES"] = domain.update_ai_mcp_profile(
        existing.get("COMPOSE_PROFILES"),
        enabled=cfg.ai_mcp_enabled,
    )
    rendered = domain.update_env_values(content, values)
    if any("\n" in value or "\r" in value for value in generated.values()):
        raise ValueError("Configuration values must not contain newlines")
    root.mkdir(parents=True, exist_ok=True)
    for relative in ("data/pgdata", "data/valkeydata", "installation", "extensions"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    if env_path.is_file():
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        shutil.copy2(env_path, root / f".env.bak.{stamp}")
    temporary = root / ".env.offline.tmp"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            temporary.chmod(0o600)
            stream.write(rendered)
        temporary.replace(env_path)
    finally:
        temporary.unlink(missing_ok=True)
    identity = root / "installation" / "instance_id"
    if not identity.is_file() or not identity.read_text(encoding="utf-8").strip():
        identity.write_text(str(uuid.uuid4()) + "\n", encoding="utf-8")
    return cfg


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("install", "update"), required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--host-dir", required=True)
    parser.add_argument("--public-url")
    parser.add_argument("--external-port")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--ai-mcp", choices=("true", "false"))
    args = parser.parse_args()
    try:
        cfg = prepare_configuration(
            Path("/dvt-lib"),
            mode=args.mode,
            version=args.version,
            host_dir=args.host_dir,
            public_url=args.public_url,
            external_port=args.external_port,
            workers=args.workers,
            ai_mcp=None if args.ai_mcp is None else args.ai_mcp == "true",
        )
    except (ValueError, OSError) as exc:
        print(f"Offline configuration failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    # Non-secret settings consumed by the Bash runner.
    print(cfg.project_name)
    print(cfg.task_workers_count)
    print(domain.render_bool(cfg.ai_mcp_enabled))


if __name__ == "__main__":
    main()
