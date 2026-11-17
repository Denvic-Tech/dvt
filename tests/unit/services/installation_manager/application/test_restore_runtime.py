import io
import runpy
import sys
import tarfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest
from fastapi import Cookie, FastAPI, HTTPException
from fastapi.testclient import TestClient
from tests.data.installation_manager.verified_staging.fixtures import (
    CORE,
    ROOT,
    make_compose,
    make_manifest,
    sign_manifest,
)

from services.gateway.update_runtime.middleware import SystemUpdateMiddleware
from services.installation_manager.application import portable_restore, restore_runtime
from services.installation_manager.application.restore_runtime import (
    FunctionalProof,
    RestoreRuntime,
)
from services.installation_manager.domain.operation_state import (
    ArtifactKind,
    Checkpoint,
    CheckpointOutcome,
    FailureReason,
    InstanceIdentity,
    Observation,
    OperationKind,
    OperationRequest,
    OperationStage,
    ReleasePin,
)
from services.installation_manager.domain.release_manifest import (
    canonical_json,
    digest_of,
    strict_json,
)
from services.installation_manager.host_bootstrap import atomic_write
from services.installation_manager.infrastructure import application_host, maintenance_archive
from services.installation_manager.infrastructure.application_host import (
    CONTEXT_ENV,
    ComposeApplicationHost,
)
from services.installation_manager.infrastructure.operation_store import OperationStore
from services.installation_manager.infrastructure.operator_wiring import wire_gateway
from services.installation_manager.infrastructure.release_verification import TrustPolicy
from services.installation_manager.infrastructure.staging_artifacts import artifact_directory

from src.schemas.http.system import SystemStateValue


def test_restored_application_requires_functional_proof_before_opening_admission(
    tmp_path, monkeypatch,
):
    store = OperationStore.for_host(tmp_path)
    identity = InstanceIdentity(uuid4(), "/test", "restore", "127.0.0.1", 18888, "http://localhost")
    store.establish_identity(identity)
    original_digest = "sha256:" + "a" * 64
    target = ReleasePin("candidate", "sha256:" + "b" * 64)
    operation = store.admit(OperationRequest(OperationKind.UPDATE, target), idempotency_key="restore")
    with store.claim(operation.id) as owner:
        owner.checkpoint(Checkpoint(OperationStage.PREPARING))
        owner.checkpoint(Checkpoint(OperationStage.PREPARED))
        owner.checkpoint(Checkpoint(OperationStage.MAINTENANCE))
        owner.checkpoint(Checkpoint(
            OperationStage.BACKUP,
            observation=Observation(source_revision="0070", source_digest=original_digest),
        ))
    (tmp_path / ".bootstrap").mkdir()
    marker = {"manifest_digest": "sha256:" + "c" * 64}
    role_image = "docker.io/library/fixture@sha256:" + "d" * 64
    images = dict.fromkeys(restore_runtime.MANAGED_ROLES | {"installation_manager"}, role_image)
    source = {
        "images": images, "profiles": [], "revision": "0070", "operation": str(uuid4()),
    }

    def prepare(*_):
        return marker, source, {"services": {role: {"environment": {},
                                                    "image": image} for role, image in images.items()}}

    monkeypatch.setattr(RestoreRuntime, "_prepare", prepare)
    monkeypatch.setattr(RestoreRuntime, "_receipt", lambda *_: "new-physical-context")
    monkeypatch.setattr(restore_runtime, "_validate_runtime", lambda *_: None)
    monkeypatch.setattr(restore_runtime, "init_container", lambda *_: str(restore_runtime.FORMAT_VERSION))
    verified = []
    opened = []

    def verify(_host, _pg, proof):
        if proof.access_cookie == "accepted":
            verified.append(proof.project)
        else:
            raise ValueError("Auth failed")

    monkeypatch.setattr(RestoreRuntime, "_verify_application", staticmethod(verify))

    class Host:
        def __init__(self, _config, directory, model, _plan, _deadline):
            self.path = directory / "application.compose.yaml"
            self.services = model["services"]

        @staticmethod
        def bind_images():
            pass

        @staticmethod
        def containers():
            return {"postgres": ["exists"], "installation_manager": ["exists"]}

        @staticmethod
        def wait_for_database():
            return "restored-postgres"

        @staticmethod
        def app_ready(*_):
            return True

        @staticmethod
        def wait_for_application(*_):
            return True

        @staticmethod
        def sql(*_):
            return "frozen"

        @staticmethod
        def database_identity(_pg):
            return "123:42"

        @staticmethod
        def resume(pg, context):
            assert store.get(operation.id).stage is OperationStage.RESUMING
            opened.append((pg, context))
            return True

    monkeypatch.setattr(restore_runtime, "ComposeApplicationHost", Host)
    runtime = RestoreRuntime(store, {"data": str(tmp_path), "temporary": str(tmp_path)}, lambda *_: None)
    assert not runtime.execute(operation.id)
    assert store.get(operation.id).stage is OperationStage.BACKUP

    assert runtime.execute(operation.id, authorize=True)
    assert store.get(operation.id).stage is OperationStage.VERIFYING
    assert not opened

    old_project = uuid4()
    assert not runtime.execute(operation.id, proof=FunctionalProof("rejected", old_project))
    assert store.get(operation.id).stage is OperationStage.VERIFYING
    failure = store.first_failure(operation.id)
    assert failure.checkpoint.reason.value == "gateway_unavailable"
    assert not opened

    assert runtime.execute(operation.id, proof=FunctionalProof("accepted", old_project))
    assert verified == [old_project]
    assert opened == [("restored-postgres", "new-physical-context")]
    assert store.get(operation.id).stage is OperationStage.SUCCEEDED
    assert store.first_failure(operation.id) == failure


def test_recovery_refuses_database_with_unexpected_revision():
    operation = SimpleNamespace(id=uuid4(), instance_id=uuid4())
    host = SimpleNamespace(
        services={role: {"environment": {}} for role in restore_runtime.MANAGED_ROLES},
        database_identity=lambda _: "123:42",
        revision=lambda _: "0071",
    )
    prior = {
        "legacy_adopted": True, "operation": str(uuid4()), "revision": "0070",
        "manifest_digest": "sha256:" + "c" * 64, "database": "456:42",
        "images": {"gateway": "fixture@sha256:" + "d" * 64},
    }
    with pytest.raises(ValueError, match="restored schema"):
        RestoreRuntime._receipt(host, "postgres", operation, prior, OperationStage.RECOVERING)



@pytest.fixture
def restored_instance(tmp_path, monkeypatch):
    # The fixture uses the real protected paths, journal pin, copy fingerprints
    # and resolved Compose file. Only Docker interactions are supplied below.
    monkeypatch.setattr(restore_runtime, "safe_path", Path)
    monkeypatch.setattr(portable_restore, "safe_path", Path)
    data = tmp_path / "restored"
    control = data / ".bootstrap"
    control.mkdir(parents=True, mode=0o700)
    for name, content in (
        ("ca.pem", b"test CA"),
        ("machine-token", b"test machine"),
        ("session-key", b"0" * 32),
    ):
        atomic_write(control / name, content)
    store = OperationStore.for_host(data)
    identity = InstanceIdentity(
        uuid4(), "/var/lib/dvt-restore-fixture", "restore", "127.0.0.1", 18888, "http://localhost",
    )
    store.establish_identity(identity)
    config = {
        "data": str(data), "project": identity.compose_project, "port": identity.manager_port,
        "temporary": str(data), "instance": str(identity.instance_id),
    }
    atomic_write(control / "host.json", canonical_json(config))
    application = "docker.io/library/fixture@sha256:" + "b" * 64
    infrastructure = "docker.io/library/fixture@sha256:" + "a" * 64
    source_manifest = make_manifest(
        make_compose(application, infrastructure=infrastructure),
        reference=application, infrastructure=infrastructure,
    )
    source_manifest["schema"]["target_revision"] = "0070"
    pin, signature = sign_manifest(source_manifest)
    signed = TrustPolicy({"beta-root": ROOT.public_key().public_bytes_raw()}).verify(signature, pin)
    images = {name: signed.platforms["linux/amd64"].images[name].reference for name in CORE}
    old = store.admit(OperationRequest(OperationKind.INSTALL, pin), idempotency_key="old-install")
    with store.claim(old.id) as owner:
        for stage in (
            OperationStage.PREPARING, OperationStage.PREPARED, OperationStage.MIGRATING,
            OperationStage.APPLYING, OperationStage.VERIFYING, OperationStage.RESUMING,
        ):
            owner.checkpoint(Checkpoint(stage))
        owner.checkpoint(Checkpoint(OperationStage.SUCCEEDED, CheckpointOutcome.VERIFIED))
    target = ReleasePin("candidate", "sha256:" + "c" * 64)
    operation = store.admit(OperationRequest(OperationKind.UPDATE, target), idempotency_key="restore")
    with store.claim(operation.id) as owner:
        owner.checkpoint(Checkpoint(OperationStage.PREPARING))
        owner.checkpoint(Checkpoint(OperationStage.PREPARED))
        owner.checkpoint(Checkpoint(OperationStage.MAINTENANCE))
        owner.checkpoint(Checkpoint(OperationStage.BACKUP, observation=Observation(
            source_revision="0070", source_digest=pin.manifest_digest,
        )))

    database = {"POSTGRES_USER": "fixture", "POSTGRES_DB": "fixture", "POSTGRES_PASSWORD": "fixture"}
    base_mounts = [
        {"type": "bind", "source": str(data / folder), "target": f"/app/{folder}"}
        for folder in ("installation", "extensions")
    ]
    services = {role: {"image": image, "environment": {}} for role, image in images.items()}
    for role in restore_runtime.MANAGED_ROLES:
        services[role].update(
            environment=database.copy(),
            depends_on={"migrate": {"condition": "service_completed_successfully"}},
        )
    for role in ("migrate", "gateway"):
        services[role].update(volumes=[dict(mount) for mount in base_mounts], networks={"dvt-net": None})
    services["migrate"].update(
        command=["python3", "-m", "services.gateway.migrate"], restart="no",
        depends_on={"postgres": {"condition": "service_healthy"}},
    )
    services["postgres"].update(environment=database, volumes=[{
        "type": "bind", "source": str(data / "pgdata"), "target": "/var/lib/postgresql/data",
    }])
    for role in ("postgres", "gateway", "ui", "valkey"):
        services[role]["healthcheck"] = {"test": ["CMD", "true"]}
    services["installation_manager"]["networks"] = {"default": None}
    model = {
        "services": services, "name": config["project"],
        "networks": {"dvt-net": {"name": "restore_dvt-net"}, "default": {
            "name": "restore_default", "ipam": {},
        }},
    }

    def seal_copy():
        compose = canonical_json(model)
        env = b"FIXTURE=1\n"
        atomic_write(data / "docker-compose.yaml", compose)
        atomic_write(data / ".env", env)
        atomic_write(control / "current-release.json", canonical_json({
            "operation": str(old.id), "instance": str(identity.instance_id),
            "release_id": pin.release_id, "manifest_digest": pin.manifest_digest,
            "compose_digest": digest_of(compose), "config_digest": digest_of(env),
            "revision": "0070", "images": images, "profiles": [],
        }))
        backup = tmp_path / "copy"
        backup.mkdir(mode=0o700)
        with tarfile.open(backup / "data.tar.gz", "w:gz") as archive:
            for name in sorted(maintenance_archive.REQUIRED_FILES):
                archive.add(data / name, arcname=name, recursive=False)
        (backup / "data.tar.gz").chmod(0o600)
        atomic_write(backup / "database.dump", b"synthetic dump")
        atomic_write(
            backup / "globals.sql",
            b"-- PostgreSQL database cluster dump\n-- PostgreSQL database cluster dump complete\n",
        )
        atomic_write(backup / "manifest.json", canonical_json({
            "format_version": 1, "operation_id": str(operation.id), "backup_id": str(operation.id),
            "instance_id": str(identity.instance_id), "compose_project": config["project"],
            "created_at": datetime.now(UTC).isoformat(), "source_revision": "0070",
            "source_digest": pin.manifest_digest,
            "source_images": {role: image for role, image in images.items() if role != "migrate"},
            "artifacts": {
                name: maintenance_archive._fingerprint(backup / name)
                for name in maintenance_archive.FILES
            },
        }))
        _, plan = portable_restore.inspect_copy(backup)
        directory = artifact_directory(store, ArtifactKind.STAGING, operation.id)
        atomic_write(directory / "restored-data.json", canonical_json({**plan, "admission": "frozen"}))
        atomic_write(directory / "restore-input.json", canonical_json({"copy": str(backup)}))
        return directory

    return store, config, operation, model, seal_copy


@pytest.mark.parametrize("wiring", [
    "saved", "saved-retry", "legacy", "partial", "wrong-source", "writeable",
    "create-host-path", "missing-file", "foreign-bind", "foreign-network",
    "shared-network", "foreign-default", "migrator",
])
def test_restore_validates_sealed_compose_and_preserves_gateway_wiring(
    restored_instance, monkeypatch, wiring,
):
    store, config, operation, model, seal_copy = restored_instance
    services = model["services"]
    gateway = services["gateway"]
    if wiring != "legacy":
        wire_gateway(services, config)
    if wiring == "partial":
        gateway["volumes"].pop()
    elif wiring == "wrong-source":
        gateway["volumes"][-1]["source"] = str(Path(config["data"]) / "foreign-token")
    elif wiring == "writeable":
        gateway["volumes"][-1]["read_only"] = False
    elif wiring == "create-host-path":
        gateway["volumes"][-1]["bind"]["create_host_path"] = True
    elif wiring == "missing-file":
        (Path(config["data"]) / ".bootstrap" / "gateway-token").unlink()
    elif wiring == "foreign-bind":
        gateway["volumes"].append({"type": "bind", "source": "/foreign", "target": "/different"})
    elif wiring == "foreign-network":
        gateway["networks"]["foreign"] = None
    elif wiring == "shared-network":
        for role in ("gateway", "migrate"):
            services[role]["networks"]["foreign"] = None
    elif wiring == "foreign-default":
        model["networks"]["default"]["name"] = "foreign_default"
    elif wiring == "migrator":
        services["migrate"]["volumes"].append(dict(gateway["volumes"][-1]))
    directory = seal_copy()
    retry = wiring == "saved-retry"
    if retry:
        marker = strict_json((directory / "restored-data.json").read_bytes())
        atomic_write(directory / restore_runtime.AUTHORIZATION, canonical_json({
            "backup_digest": marker["manifest_digest"],
        }))
        with store.claim(operation.id) as owner:
            owner.checkpoint(Checkpoint(OperationStage.RECOVERY_REQUIRED))
            owner.checkpoint(Checkpoint(OperationStage.RECOVERING))

    calls = []
    monkeypatch.setattr(application_host, "StagingDocker", lambda *_: None)
    monkeypatch.setattr(ComposeApplicationHost, "bind_images", lambda _: None)
    monkeypatch.setattr(ComposeApplicationHost, "containers", lambda _: {})
    monkeypatch.setattr(ComposeApplicationHost, "up", lambda _, role=None, **__: calls.append(role))
    monkeypatch.setattr(ComposeApplicationHost, "wait_for_database", lambda _: "fixture-db")
    monkeypatch.setattr(ComposeApplicationHost, "app_ready", lambda *_: False)
    monkeypatch.setattr(ComposeApplicationHost, "wait_for_application", lambda *_: True)
    monkeypatch.setattr(RestoreRuntime, "_receipt", lambda *_: "new-database-context")
    monkeypatch.setattr(restore_runtime, "init_container", lambda *_: str(restore_runtime.FORMAT_VERSION))

    runtime = RestoreRuntime(store, config, lambda *_: None)
    if wiring not in {"legacy", "saved", "saved-retry"}:
        assert not runtime.execute(operation.id, authorize=True)
        assert store.get(operation.id).stage is OperationStage.RECOVERING
        assert store.first_failure(operation.id).checkpoint.reason is FailureReason.COMPOSE
        assert calls == []
        return

    assert runtime.execute(operation.id, authorize=not retry), store.first_failure(operation.id)
    assert store.get(operation.id).stage is OperationStage.VERIFYING
    assert calls == ["postgres", "installation_manager", None]
    deployed = strict_json((directory / "application.compose.yaml").read_bytes())
    for role in ("gateway", "migrate"):
        original = services[role]
        assert deployed["services"][role] == {
            **original, "environment": {**original["environment"], CONTEXT_ENV: "new-database-context"},
        }
    assert deployed["networks"] == model["networks"]
    assert strict_json((Path(config["data"]) / "docker-compose.yaml").read_bytes()) == model



@pytest.mark.parametrize("case", ["valid", "wrong-project", "wrong-extensions", "invalid-cookie"])
def test_restore_auth_probe_reads_only_local_routes_while_public_gate_is_frozen(
    tmp_path, monkeypatch, case,
):
    project_id = str(uuid4())
    token = "fixture.auth.cookie"
    events = []

    async def user_info(access_token: str = Cookie()) -> dict:
        if access_token != token:
            raise HTTPException(401)
        return {"role": "superadmin"}

    async def project(project_id_from_path: str, access_token: str = Cookie()) -> dict:
        events.append(("project", project_id_from_path))
        if access_token != token or project_id_from_path != project_id:
            raise HTTPException(404)
        return {"id": project_id}

    async def empty_projects(access_token: str = Cookie()) -> list:
        assert access_token == token
        return []

    async def extensions(access_token: str = Cookie()) -> list:
        events.append(("extensions",))
        assert access_token == token
        return [
            {"name": "restored-extension", "is_installed": True},
            {"name": "ignored-extension", "is_installed": False},
        ]

    async def by_id(project_id: str, access_token: str = Cookie()) -> dict:
        return await project(project_id, access_token)

    monitor = SimpleNamespace(snapshot=SimpleNamespace(
        state=SystemStateValue.UPDATING, retry_after_sec=2,
    ))
    public = FastAPI(root_path="/api")
    public.add_middleware(SystemUpdateMiddleware, monitor=monitor)
    public.add_api_route("/user/info", user_info, methods=["GET"])
    public.add_api_route("/projects/{project_id}", by_id, methods=["GET"])
    public.add_api_route("/extensions", extensions, methods=["GET"])
    with TestClient(public) as client:
        assert client.get(f"/api/projects/{project_id}").status_code == 503
        assert client.get("/api/extensions").status_code == 503

        def open_loopback(request, timeout):
            url = urlsplit(request.full_url)
            assert (url.hostname, url.port, url.path) == ("127.0.0.1", 8000, "/api/user/info")
            assert timeout == 6 and request.get_method() == "GET"
            response = client.get(url.path, headers=dict(request.header_items()))
            response.raise_for_status()
            return io.BytesIO(response.content)

        monkeypatch.setattr(
            urllib.request, "build_opener", lambda *_: SimpleNamespace(open=open_loopback),
        )
        monkeypatch.setitem(sys.modules, "services.gateway.auth_app", SimpleNamespace(
            create_auth_app=lambda: events.append(("auth",)),
        ))
        monkeypatch.setitem(sys.modules, "services.gateway.routes.project.crud", SimpleNamespace(
            get_project_by_id=by_id, get_projects=empty_projects,
        ))
        monkeypatch.setitem(sys.modules, "services.gateway.routes.extensions", SimpleNamespace(
            list_extensions=extensions,
        ))
        selected = str(uuid4()) if case == "wrong-project" else project_id
        monkeypatch.setattr(sys, "argv", ["probe", "8000", selected])
        monkeypatch.setattr(sys, "stdin", io.StringIO(canonical_json({
            "access_token": "invalid" if case == "invalid-cookie" else token,
            "extensions": ["different"] if case == "wrong-extensions" else ["restored-extension"],
        }).decode()))
        path = tmp_path / "probe.py"
        path.write_text(restore_runtime.AUTH_PROBE, encoding="utf-8")
        if case == "valid":
            runpy.run_path(str(path), run_name="__main__")
            assert events == [("auth",), ("project", project_id), ("extensions",)]
        elif case == "wrong-extensions":
            with pytest.raises(SystemExit) as failure:
                runpy.run_path(str(path), run_name="__main__")
            assert failure.value.code == 1
        else:
            with pytest.raises(httpx.HTTPStatusError) as failure:
                runpy.run_path(str(path), run_name="__main__")
            assert failure.value.response.status_code == (401 if case == "invalid-cookie" else 404)
            assert events == ([] if case == "invalid-cookie" else [("auth",), ("project", selected)])
        assert monitor.snapshot.state is SystemStateValue.UPDATING
