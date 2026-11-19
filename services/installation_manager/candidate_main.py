"""Image entrypoints for the candidate web manager, bootstrap and executor."""

from __future__ import annotations

import os
import secrets
import ssl
import sys
from pathlib import Path
from uuid import UUID

import uvicorn

from .application.application_apply import ApplicationApply
from .application.maintenance_backup import MaintenanceBackup
from .application.recovery import cancel_preparation
from .application.restore_runtime import RestoreRuntime
from .candidate_api import create_app
from .candidate_auth import CandidateAuth
from .candidate_executor import _probe, execute
from .domain.operation_state import InstanceIdentity
from .host_bootstrap import CONTROL, atomic_write, load_host
from .infrastructure.operation_files import _require_regular_file
from .infrastructure.operation_store import FORMAT_VERSION, OperationStore


def _store(config: dict) -> OperationStore:
    store = OperationStore.for_host(Path(config["data"]))
    expected = _identity(config)
    if store.identity() != expected:
        raise ValueError("The journal does not belong to the configured instance")
    return store


def _identity(config: dict) -> InstanceIdentity:
    return InstanceIdentity(
        UUID(config["instance"]),
        config["data"],
        config["project"],
        config["address"],
        config["port"],
        config["public_url"],
    )


def _tls(directory: Path) -> dict[str, str]:
    for name in ("cert.pem", "key.pem", "ca.pem"):
        _require_regular_file((directory / name).lstat())
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(directory / "cert.pem", directory / "key.pem")
    # Test that the supplied CA and localhost identity can complete a TLS handshake.
    client = ssl.create_default_context(cafile=directory / "ca.pem")
    server_in, server_out, client_in, client_out = (ssl.MemoryBIO() for _ in range(4))
    connection = (
        (context.wrap_bio(server_in, server_out, server_side=True), server_out, client_in),
        (
            client.wrap_bio(client_in, client_out, server_hostname="localhost"),
            client_out,
            server_in,
        ),
    )
    for _ in range(8):
        ready = 0
        for endpoint, outgoing, incoming in connection:
            try:
                endpoint.do_handshake()
                ready += 1
            except ssl.SSLWantReadError:
                pass
            if data := outgoing.read():
                incoming.write(data)
        if ready == 2:
            return {
                "ssl_certfile": str(directory / "cert.pem"),
                "ssl_keyfile": str(directory / "key.pem"),
            }
    raise ValueError("The localhost certificate could not complete a TLS handshake")


def run(action: str, data: Path, operation_id: str | None = None) -> None:
    os.umask(0o077)
    config = load_host(data)
    directory = data / CONTROL
    tls = {}
    if (
        action in {"candidate-init", "candidate-inspect", "candidate-web"}
        and config.get("manager_http") is not True
    ):
        tls = _tls(directory)
    if action == "candidate-init":
        OperationStore.for_host(data).establish_identity(_identity(config))
        for name, contents in (
            ("machine-token", secrets.token_urlsafe(32).encode()),
            ("session-key", secrets.token_bytes(32)),
        ):
            if not (directory / name).exists():
                atomic_write(directory / name, contents)
        return
    store = _store(config)
    if action in {"candidate-inspect", "candidate-inspect-wizard"}:
        CandidateAuth(config)
        sys.stdout.write(f"{FORMAT_VERSION}\n")
        return
    if action == "candidate-pair":
        sys.stdout.write(CandidateAuth(config).issue_pairing() + "\n")
    elif action == "candidate-executor" and operation_id is not None:
        execute(config, store, UUID(operation_id))
    elif action == "candidate-cancel-preparation" and operation_id is not None:
        cancel_preparation(store, UUID(operation_id))
    elif action == "candidate-recover-manager" and operation_id is not None:
        ApplicationApply(store, config, _probe).recover_manager(UUID(operation_id))
    elif action == "candidate-return-to-source" and operation_id is not None:
        ApplicationApply(store, config, _probe).return_to_source(UUID(operation_id))
    elif action == "candidate-restore-start" and operation_id is not None:
        RestoreRuntime(store, config, _probe).execute(UUID(operation_id), authorize=True)
    elif action in {"candidate-maintenance", "candidate-maintenance-extend",
                    "candidate-maintenance-defer"} and operation_id is not None:
        MaintenanceBackup(store, config).execute(
            UUID(operation_id),
            confirm=action == "candidate-maintenance",
            extend=action == "candidate-maintenance-extend",
            defer=action == "candidate-maintenance-defer",
        )
        operation = store.get(UUID(operation_id))
        if operation is not None and operation.observation.backup_id == operation.id:
            execute(config, store, operation.id)
    elif action == "candidate-web":
        path = Path(os.environ.get("UPDATE_SERVICE_STATIC_DIR", "/static"))
        app = create_app(config, store, path)
        uvicorn.run(
            app, host="0.0.0.0", port=8000, access_log=False, proxy_headers=False, **tls
        )
    else:
        raise ValueError("Unknown installation manager mode")
