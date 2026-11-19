"""Run only on a disposable Linux host with local Docker access."""
from __future__ import annotations

import json
import os
import socket
import ssl
import subprocess
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from services.installation_manager.application.verified_staging import VerifiedStaging
from services.installation_manager.domain.operation_state import (
    Checkpoint, FailureReason, InstanceIdentity, OperationKind, OperationRequest, OperationStage,
)
from services.installation_manager.domain.release_manifest import StagingError
from services.installation_manager.infrastructure.operation_store import OperationStore
from services.installation_manager.infrastructure.release_verification import TrustPolicy
from services.installation_manager.infrastructure.staging_artifacts import save_config
from services.installation_manager.infrastructure.staging_commands import Deadline, RetryPolicy
from services.installation_manager.infrastructure.staging_compose import ObservedRelease, effective_config
from services.installation_manager.infrastructure.staging_docker import StagingDocker
from services.installation_manager.infrastructure.staging_downloads import ReleaseDownloader
from services.installation_manager.infrastructure.staging_host import HostPaths
from tests.data.installation_manager.verified_staging.fixtures import (
    BOOTSTRAP, CORE, ROOT, TEST_SECRET, make_compose, make_manifest, sign_manifest,
)


def command(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, timeout=90, **kwargs).stdout


def child_manifest(tag):
    repo = "docker.io/library/busybox"
    obj = json.loads(command("docker", "buildx", "imagetools", "inspect", "--raw", f"{repo}:{tag}"))
    match = next(
        row for row in obj["manifests"]
        if row.get("platform", {}).get("architecture") == "amd64"
        and row["platform"].get("os") == "linux"
    )
    return f"{repo}@{match['digest']}"


def free_port():
    with socket.socket(socket.AF_INET) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.server.abort_once:
            self.server.abort_once = False
            self.server.interruptions += 1
            self.connection.shutdown(socket.SHUT_RDWR)
            self.close_connection = True
            return
        status, payload = self.server.responses.get(self.path, (404, b""))
        self.send_response(status)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def probe(port):
    request = urllib.request.Request(f"http://127.0.0.1:{port}/witness.txt")
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.read() == b"still running\n"


def main():
    base = Path(os.environ.get("DVT_STAGE02_TMP", "/tmp"))
    with tempfile.TemporaryDirectory(prefix="dvt-stage02-", dir=base) as directory:
        run(Path(directory))


def run(work):
    data, backup, temp = [work / name for name in ("data", "backup", "temporary")]
    for path in (data, backup, temp, data / "data/pgdata", data / "data/valkeydata"):
        path.mkdir(parents=True, exist_ok=True)
    (data / ".env").write_text("DVT_VERSION=1.23.0\n")
    config_dir = work / "docker-config"
    config_dir.mkdir()
    key, cert = (work / "tls.key", work / "tls.crt")
    command(
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-keyout", str(key), "-out", str(cert), "-subj", "/CN=127.0.0.1",
        "-addext", "subjectAltName=IP:127.0.0.1",
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    server.abort_once = False
    server.interruptions = 0
    server.responses = {}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"https://127.0.0.1:{server.server_port}"
    port, manager_port = free_port(), free_port()
    while port == manager_port:
        manager_port = free_port()
    project = "dvt_stage02_smoke_" + uuid4().hex[:12]
    source = child_manifest("1.37.0-musl")
    target = child_manifest("1.37.0-glibc")
    docker = StagingDocker(work, config_dir, registry_hosts=frozenset({"docker.io", "registry.invalid"}))
    policy = RetryPolicy(total_seconds=65, io_seconds=12, attempts=2, initial_delay=0.05)
    info = docker.info(Deadline(policy))
    containerd = Path(os.environ["DVT_STAGE02_CONTAINERD"]) if "DVT_STAGE02_CONTAINERD" in os.environ else None
    os_release = Path(os.environ.get("DVT_STAGE02_OS_RELEASE", "/etc/os-release"))
    trust = TrustPolicy({"beta-root": ROOT.public_key().public_bytes_raw()})
    fetch = ReleaseDownloader(frozenset({origin}), cert)
    store = OperationStore.for_host(data)
    identity = InstanceIdentity(uuid4(), str(data), project, "127.0.0.1", manager_port, f"http://127.0.0.1:{port}")
    store.establish_identity(identity)
    values = {
        "DVT_AI_MCP_ENABLED": "true", "COMPOSE_PROFILES": "ai-mcp",
        "DVT_AI_MCP_INTERNAL_SECRET": TEST_SECRET, "DVT_POSTGRES_PASSWORD": "beta-test-postgres",
        "DVT_EXTERNAL_PORT": str(port),
    }
    config_id = save_config(store, values)
    staging = VerifiedStaging(store, trust, fetch, docker, HostPaths(temp, backup, containerd, os_release), "1.23.0", policy)

    def without_access(compose):
        return compose.replace(b"      - /var/run/docker.sock:/var/run/docker.sock\n", b"")

    running = work / "witness.yaml"
    running.write_bytes(without_access(make_compose(source)).replace(
        b'command: ["httpd", "-f", "-p", "80"]',
        b'command: ["sh", "-c", "printf \'still running\\\\n\' >/witness.txt && exec httpd -f -p 80 -h /"]',
    ))
    observed = ObservedRelease(
        version="1.23.0", revision="0068", pin=None,
        images=dict.fromkeys((name for name in CORE if name != "migrate"), source),
    )
    candidate = None
    main_compose = [
        "docker", "--config", str(config_dir), "compose", "--project-name", project,
        "--env-file", "/dev/null", "--file", str(running),
    ]
    clean_config, _ = effective_config(
        values, identity, OperationRequest(OperationKind.UPDATE, sign_manifest(
            make_manifest(make_compose(source)),
        )[0], ai_mcp_enabled=False), "1.23.0",
    )
    clean = {"PATH": os.environ["PATH"], **clean_config}
    preexisting = {ref: docker.local_image(ref, "linux/amd64", Deadline(policy)) for ref in (source, target)}

    def attempt(case, wanted=None, modified=None, ref=target, use_staging=staging):
        compose = without_access(make_compose(ref, infrastructure=source))
        manifest = make_manifest(compose, origin=origin, reference=ref, infrastructure=source)
        if modified:
            modified(manifest)
        pin, envelope = sign_manifest(manifest)
        server.responses.update({
            "/manifest.json": (200, envelope), "/compose.yaml": (200, compose), "/bootstrap.sh": (200, BOOTSTRAP),
        })
        op = store.admit(OperationRequest(OperationKind.UPDATE, pin, config_id=config_id), idempotency_key=case)
        try:
            result = use_staging.prepare(op.id, origin + "/manifest.json", observed=observed)
        except StagingError as error:
            assert wanted is not None and error.reason in wanted, (case, error.reason, str(error))
            assert TEST_SECRET not in str(error)
            print(f"{case}: {error.reason.value}", flush=True)
            result = None
        else:
            assert wanted is None
            assert store.get(op.id).stage is OperationStage.PREPARED
            assert result.environment["DVT_AI_MCP_INTERNAL_SECRET"] == TEST_SECRET
            assert TEST_SECRET not in repr(result)
            print(f"{case}: prepared", flush=True)
        probe(port)
        assert (data / ".env").read_text() == "DVT_VERSION=1.23.0\n"
        with store.claim(op.id) as owner:
            owner.checkpoint(Checkpoint(OperationStage.CANCELLED))
        return result

    try:
        command(*main_compose, "up", "-d", env=clean)
        probe(port)
        print(f"Docker {info['ServerVersion']}, Compose {docker.compose_version(Deadline(policy))}", flush=True)
        no_ca = VerifiedStaging(
            store, trust, ReleaseDownloader(frozenset({origin})), docker, staging.paths, "1.23.0", policy,
        )
        attempt("self-signed-cert", {FailureReason.TLS}, use_staging=no_ca)
        attempt("registry-unreachable", {FailureReason.REGISTRY_UNAVAILABLE}, ref="registry.invalid/dvt/test@sha256:" + "a" * 64)
        attempt(
            "space-deficit", {FailureReason.DISK_SPACE},
            modified=lambda manifest: manifest["environment"]["base"].update(data_reserve_bytes=2**60),
        )
        attempt(
            "inode-deficit", {FailureReason.INODES},
            modified=lambda manifest: manifest["environment"]["base"].update(reserve_inodes=2**50),
        )
        server.abort_once = True
        os.environ["DVT_AI_MCP_INTERNAL_SECRET"] = ""
        candidate = attempt("retry-and-pinned-image-preflight")
        assert server.interruptions == 1
        assert candidate.pin.manifest_digest == store.history()[0].request.release.manifest_digest
        print("running workload and working configuration preserved after every attempt", flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        command(*main_compose, "down", "--volumes", env=clean)
        for ref, existed in preexisting.items():
            if not existed and docker.local_image(ref, "linux/amd64", Deadline(policy)):
                command("docker", "image", "rm", ref)


if __name__ == "__main__":
    main()
