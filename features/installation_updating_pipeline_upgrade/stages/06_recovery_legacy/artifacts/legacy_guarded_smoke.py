"""Exercise legacy manager adoption on a guarded, test-signed release with local Docker.

Use a new /var/tmp/dvt-s06-<12-hex> scope, a signed template with parameterized data
paths and no container_name, and preloaded pinned images for the source and managers.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet

from services.installation_manager.application import legacy_adopt
from services.installation_manager.application.application_apply import _dotenv
from services.installation_manager.application.legacy_transition import LegacyPolicy, observe
from services.installation_manager.candidate_executor import _probe
from services.installation_manager.domain.operation_state import ReleasePin
from services.installation_manager.domain.release_manifest import digest_of, strict_json
from services.installation_manager.host_bootstrap import check_project, docker, safe_path
from services.installation_manager.infrastructure.release_verification import (
    TrustPolicy,
    verify_file,
)
from services.installation_manager.infrastructure.staging_compose import validate_template

FOLDER = re.compile(r"dvt-s06-[0-9a-f]{12}")


def _verify_scope(model, root, expected_binds):
    if model["name"] != root.name:
        raise ValueError("Fixture scope mismatch")
    for name, role in model["services"].items():
        if any(key in role for key in ("container_name", "privileged", "network_mode", "build")):
            raise ValueError("The signed fixture contains an unsupported global setting")
        for mount in role.get("volumes", []):
            if name == "installation_manager" and mount["source"] == "/var/run/docker.sock":
                continue
            if mount["type"] != "bind" or not Path(mount["source"]).is_relative_to(root):
                raise ValueError("A fixture service mounts an external path")
        for port in role.get("ports", []):
            bind = (port.get("host_ip"), str(port["published"]))
            if bind != expected_binds.get(name):
                raise ValueError("The signed fixture uses an unapproved host bind")
    for network in model["networks"].values():
        if network.get("external") or not network["name"].startswith(root.name + "_"):
            raise ValueError("The fixture may only create scoped local networks")


def _manifest(path, trust):
    raw = path.read_bytes()
    release = strict_json(raw)["payload"]["release_id"]
    pin = ReleasePin(release, digest_of(raw))
    return pin, trust.verify(raw, pin)


def _fixture(args):
    os.umask(0o077)
    root = safe_path(args.scope)
    if os.geteuid() or root.parent != Path("/var/tmp") or not FOLDER.fullmatch(root.name):
        raise ValueError("Use root and a new /var/tmp/dvt-s06-<12 lowercase hex digits>")
    check_project(root.name)
    root.mkdir(mode=0o700)
    data = root / "instance"
    for directory in (data, root / "tls", root / "backup", root / "tmp"):
        directory.mkdir(mode=0o700)
    for name in ("installation", "extensions"):
        (data / name).mkdir(mode=0o700)
    identity = uuid4()
    (data / "installation" / "instance_id").write_text(str(identity) + "\n")

    trust = TrustPolicy.from_document(strict_json(args.trust.read_bytes()))
    pin, source = _manifest(args.source, trust)
    _, target = _manifest(args.target, trust)
    distribution = source.platforms["linux/amd64"]
    template = args.compose.read_bytes()
    verify_file(template, distribution.compose, "legacy fixture Compose")
    validate_template(template)
    compose = data / "docker-compose.yaml"
    compose.write_bytes(template)

    origin = f"http://localhost:{args.app_port}"
    env = {
        "DVT_VERSION": source.version, "DVT_LIB_DIR": str(data), "DVT_PUBLIC_URL": origin,
        "DVT_EXTERNAL_PORT": str(args.app_port),
        "DVT_INSTALLATION_MANAGER_EXTERNAL_PORT": str(args.manager_port),
        "DVT_INSTALLATION_MANAGER_BIND_ADDRESS": "127.0.0.1",
        "DVT_NETWORK_NAME": root.name + "_app",
        "DVT_NETWORK_EXTERNAL": "false", "DVT_AI_MCP_ENABLED": "false",
        "DVT_POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        "DVT_VALKEY_PASSWORD": secrets.token_urlsafe(24),
        "DVT_FERNET_KEY": Fernet.generate_key().decode(),
    }
    working = data / ".env"
    working.write_bytes(_dotenv(env))
    cli = (
        "compose", "--project-name", root.name, "--project-directory", str(data), "--env-file",
        str(working), "--file", str(compose),
    )
    model = json.loads(docker(*cli, "--profile", "*", "config", "--format", "json").stdout)
    _verify_scope(model, root, {
        "proxy": ("127.0.0.1", str(args.app_port)),
        "installation_manager": ("127.0.0.1", str(args.manager_port)),
    })
    subprocess.run(
        [
            "openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048", "-days", "1", "-subj",
            "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
            "-keyout", str(root / "tls" / "key.pem"), "-out", str(root / "tls" / "cert.pem"),
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
    )
    (root / "tls" / "ca.pem").write_bytes((root / "tls" / "cert.pem").read_bytes())
    try:
        docker(*cli, "up", "--wait", "--wait-timeout", "240", "--no-build", "--pull", "never", timeout=260)
        before = legacy_adopt._containers(root.name)
        policy = LegacyPolicy.model_validate({
            "format_version": 1,
            "predecessors": [{
                "version": source.version, "revision": source.database_schema.target_revision,
                "images": {
                    role: distribution.images[role].reference
                    for role in before if role != "migrate"
                },
            }],
        })
        report = observe(data, root.name, policy, target=target)
        if report["blockers"]:
            raise RuntimeError(json.dumps({"blockers": report["blockers"]}))
        info = json.loads(docker("info", "--format", "{{json .}}").stdout)
        config = {
            "version": 1, "instance": str(identity), "data": str(data), "project": root.name,
            "address": "127.0.0.1", "port": args.manager_port, "public_url": origin,
            "manager": distribution.images["installation_manager"].reference,
            "candidate": args.candidate_manager, "executor": args.executor,
            "docker_root": info["DockerRootDir"],
            "containerd_root": str(args.containerd_root) if args.containerd_root else None,
            "temporary": str(root / "tmp"), "backup": str(root / "backup"),
        }
        store, operation = legacy_adopt._prepare(
            data, root.name, config, root / "tls", policy, source, target, pin,
        )
        if not legacy_adopt.execute(config, store, operation, _probe):
            raise RuntimeError("A guarded adoption did not finish")
        after = legacy_adopt._containers(root.name)
        if (
            legacy_adopt._application_containers(before) != legacy_adopt._application_containers(after)
            or before["installation_manager"][0]["Id"] == after["installation_manager"][0]["Id"]
            or store.identity().instance_id != identity
            or store.get(operation).observation.observed_revision != source.database_schema.target_revision
            or working.read_bytes() != _dotenv(env)
        ):
            raise RuntimeError("The guarded adoption changed the original installation")
        return {
            "operation_id": str(operation), "observed_version": source.version,
            "revision": source.database_schema.target_revision,
            "digest": pin.manifest_digest, "original_application_containers": "preserved",
            "manager_bind": f"127.0.0.1:{args.manager_port}",
            "protected_journal": "verified", "identity": "preserved",
        }
    finally:
        docker(*cli, "down", "--remove-orphans", timeout=180)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("scope", "source", "target", "compose", "trust", "containerd-root"):
        parser.add_argument(f"--{name}", type=Path, required=name != "containerd-root")
    parser.add_argument("--app-port", type=int, default=18148)
    parser.add_argument("--manager-port", type=int, default=19148)
    parser.add_argument("--candidate-manager", required=True)
    parser.add_argument("--executor", required=True)
    args = parser.parse_args()
    try:
        result = _fixture(args)
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
        # Preserve classified Docker observation blockers, keeping Compose and env errors private.
        reason = str(exc) if str(exc).startswith('{"blockers":') else "Guarded fixture failed"
        sys.stderr.write(reason + "\n")
        return 1
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
