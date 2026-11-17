"""Public beta fixtures. The deterministic private seeds below are test keys only."""

from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.installation_manager.domain.operation_state import ReleasePin
from services.installation_manager.domain.release_manifest import canonical_json, digest_of
from services.installation_manager.infrastructure.release_verification import (
    KEY_CONTEXT,
    MANIFEST_CONTEXT,
)

ROOT = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
SIGNER = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
NOW = datetime(2026, 11, 16, tzinfo=UTC)
ORIGIN = "https://releases.dvt-beta.test"
SOURCE_IMAGE = "docker.io/library/busybox@sha256:" + "1" * 64
TARGET_IMAGE = "docker.io/library/busybox@sha256:" + "2" * 64
BOOTSTRAP = b"#!/bin/sh\n# DVT test fixture, never executed by staging.\n"
CORE = (
    "postgres",
    "valkey",
    "gateway",
    "migrate",
    "installation_manager",
    "proxy",
    "orchestrator",
    "task-worker",
    "project-scheduler",
    "ui",
)
TEST_SECRET = "beta-fixture-only-mcp-secret-${literal}"


def make_compose(reference: str, *, infrastructure: str | None = None) -> bytes:
    infrastructure = infrastructure or reference
    return f"""services:
  postgres:
    image: {infrastructure}
    command: ["sleep", "600"]
    environment:
      POSTGRES_PASSWORD: ${{DVT_POSTGRES_PASSWORD:?required}}
    volumes:
      - ${{DVT_LIB_DIR}}/data/pgdata:/var/lib/postgresql/data
  valkey:
    image: {infrastructure}
    command: ["sleep", "600"]
    volumes:
      - ${{DVT_LIB_DIR}}/data/valkeydata:/data
  gateway:
    image: {reference}
    command: ["sleep", "600"]
    environment:
      DVT_AI_MCP_ENABLED: ${{DVT_AI_MCP_ENABLED}}
      DVT_AI_MCP_INTERNAL_SECRET: ${{DVT_AI_MCP_INTERNAL_SECRET:-}}
  migrate:
    image: {reference}
    command: ["true"]
  installation_manager:
    image: {reference}
    command: ["sleep", "600"]
    ports:
      - "${{DVT_INSTALLATION_MANAGER_BIND_ADDRESS}}:${{DVT_INSTALLATION_MANAGER_EXTERNAL_PORT}}:8000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ${{DVT_LIB_DIR}}:/dvt-lib
  orchestrator:
    image: {reference}
    command: ["sleep", "600"]
  task-worker:
    image: {reference}
    command: ["sleep", "600"]
    scale: ${{DVT_TASK_WORKERS_COUNT:-1}}
  project-scheduler:
    image: {reference}
    command: ["sleep", "600"]
  ui:
    image: {reference}
    command: ["sleep", "600"]
  proxy:
    image: {reference}
    command: ["httpd", "-f", "-p", "80"]
    ports:
      - "127.0.0.1:${{DVT_EXTERNAL_PORT}}:80"
  dvt-ai-mcp:
    image: {reference}
    profiles: ["ai-mcp"]
    command: ["sleep", "600"]
    environment:
      DVT_AI_MCP_INTERNAL_SECRET: ${{DVT_AI_MCP_INTERNAL_SECRET:-}}
""".encode()


def make_manifest(
    compose: bytes,
    *,
    origin: str = ORIGIN,
    reference: str = TARGET_IMAGE,
    infrastructure: str = SOURCE_IMAGE,
) -> dict:
    def asset(name, data):
        return {"url": f"{origin}/{name}", "size": len(data), "digest": digest_of(data)}

    profile = {
        "min_cpus": 1,
        "min_ram_bytes": 256 * 1024 * 1024,
        "docker_reserve_bytes": 2 * 1024 * 1024,
        "data_reserve_bytes": 512 * 1024,
        "temporary_bytes": 1024 * 1024,
        "reserve_inodes": 20,
        "max_task_workers": 2,
    }
    images = {
        name: {
            "reference": infrastructure if name in {"postgres", "valkey"} else reference,
            "compressed_bytes": 4 * 1024 * 1024,
            "unpacked_bytes": 8 * 1024 * 1024,
            "unpacked_inodes": 100,
        }
        for name in (*CORE, "dvt-ai-mcp")
    }
    return {
        "format_version": 1,
        "release_id": "dvt-1.24.0-beta-fixture",
        "version": "1.24.0",
        "channel": "stable",
        "backend_sha": "a" * 40,
        "ui_sha": "b" * 40,
        "issued_at": "2026-01-01T00:00:00Z",
        "expires_at": "2030-01-01T00:00:00Z",
        "platforms": {
            "linux/amd64": {
                "compose": asset("compose.yaml", compose),
                "bootstrap": asset("bootstrap.sh", BOOTSTRAP),
                "images": images,
            },
        },
        "environment": {
            "distributions": {"debian": ["13"], "ubuntu": ["24.04"]},
            "min_docker": "29.0.0",
            "min_compose": "2.30.0",
            "pull_parallelism": 2,
            "base": profile,
            "profiles": {"ai-mcp": dict(profile, max_task_workers=1)},
        },
        "compatibility": {
            "manager_version": "1.24.0",
            "executor_version": "1.24.0",
            "minimum_preparer_version": "1.23.0",
            "journal_format": 1,
        },
        "schema": {
            "target_revision": "0069",
            "initial_install": True,
            "from_releases": [
                {
                    "version": "1.23.0",
                    "revision": "0068",
                    "migration": "from_revision",
                    "rollback": "restore_backup",
                }
            ],
        },
    }


def sign_manifest(
    manifest: dict,
    signer: Ed25519PrivateKey = SIGNER,
    root_key: Ed25519PrivateKey = ROOT,
    key_changes: dict | None = None,
) -> tuple[ReleasePin, bytes]:
    cert = {
        "root_id": "beta-root",
        "key_id": "beta-online-1",
        "public_key": signer.public_key().public_bytes_raw().hex(),
        "valid_from": "2025-01-01T00:00:00Z",
        "valid_until": "2032-01-01T00:00:00Z",
        **(key_changes or {}),
    }
    content = canonical_json(
        {
            "payload": manifest,
            "signing_key": cert,
            "key_signature": root_key.sign(KEY_CONTEXT + canonical_json(cert)).hex(),
            "manifest_signature": signer.sign(MANIFEST_CONTEXT + canonical_json(manifest)).hex(),
        }
    )
    return ReleasePin(manifest["release_id"], digest_of(content)), content


if __name__ == "__main__":
    directory = Path(__file__).parent
    compose = make_compose(TARGET_IMAGE, infrastructure=SOURCE_IMAGE)
    pin, envelope = sign_manifest(make_manifest(compose))
    (directory / "compose.yaml").write_bytes(compose)
    (directory / "bootstrap.sh").write_bytes(BOOTSTRAP)
    (directory / "manifest.json").write_bytes(envelope + b"\n")
    # The pin covers the exact bytes of the published envelope, including its final newline.
    (directory / "trust.json").write_bytes(
        canonical_json(
            {
                "release_id": pin.release_id,
                "manifest_digest": digest_of(envelope + b"\n"),
                "roots": {"beta-root": ROOT.public_key().public_bytes_raw().hex()},
            }
        )
        + b"\n"
    )
