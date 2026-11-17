from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tests.data.installation_manager.verified_staging.fixtures import (
    BOOTSTRAP,
    CORE,
    NOW,
    ORIGIN,
    ROOT,
    SOURCE_IMAGE,
    TARGET_IMAGE,
    TEST_SECRET,
    make_compose,
    make_manifest,
    sign_manifest,
)

from services.installation_manager.application import verified_staging
from services.installation_manager.application.verified_staging import VerifiedStaging
from services.installation_manager.domain.operation_state import (
    CheckpointOutcome,
    FailureReason,
    InstanceIdentity,
    OperationConflict,
    OperationKind,
    OperationRequest,
    OperationStage,
    OwnershipConflict,
    ReleasePin,
)
from services.installation_manager.domain.release_manifest import (
    StagingError,
    canonical_json,
    digest_of,
)
from services.installation_manager.infrastructure import staging_compose, staging_host
from services.installation_manager.infrastructure.operation_store import OperationStore
from services.installation_manager.infrastructure.operator_wiring import operator_binds
from services.installation_manager.infrastructure.release_verification import TrustPolicy
from services.installation_manager.infrastructure.staging_artifacts import save_config
from services.installation_manager.infrastructure.staging_compose import ObservedRelease
from services.installation_manager.infrastructure.staging_host import (
    FilesystemBudget,
    HostPaths,
    check_filesystems,
)

TRUST = TrustPolicy({"beta-root": ROOT.public_key().public_bytes_raw()})
MANIFEST_URL = ORIGIN + "/manifest.json"
APP_PORT = 14080
MANAGER_PORT = 14888


def test_published_fixture_and_rotated_key() -> None:
    directory = Path(__file__).parents[4] / "data" / "installation_manager" / "verified_staging"
    trust_data = json.loads((directory / "trust.json").read_bytes())
    content = (directory / "manifest.json").read_bytes()
    pin = ReleasePin(trust_data["release_id"], trust_data["manifest_digest"])
    trust = TrustPolicy({key: bytes.fromhex(value) for key, value in trust_data["roots"].items()})
    verified = trust.verify(content, pin, now=NOW)
    assert verified.platforms["linux/amd64"].compose.digest == digest_of(
        (directory / "compose.yaml").read_bytes()
    )
    assert verified.platforms["linux/amd64"].bootstrap.digest == digest_of(
        (directory / "bootstrap.sh").read_bytes()
    )
    rotation = Ed25519PrivateKey.from_private_bytes(b"\x80" * 32)
    new_pin, new_content = sign_manifest(verified.model_dump(mode="json", by_alias=True), rotation)
    assert trust.verify(new_content, new_pin, now=NOW) == verified
    blocked = replace(
        trust, revoked_signers=frozenset({digest_of(rotation.public_key().public_bytes_raw())})
    )
    with pytest.raises(StagingError, match="trust chain"):
        blocked.verify(new_content, new_pin, now=NOW)
    assert blocked.verify(content, pin, now=NOW) == verified
    with pytest.raises(StagingError, match="validity interval"):
        trust.verify(content, pin, now=datetime(2030, 1, 1, tzinfo=UTC))


@pytest.mark.parametrize("mutation", ["sig", "key", "bytes", "duplicate", "release"])
def test_pin_and_trust_fail_closed(mutation: str) -> None:
    pin, content = sign_manifest(
        make_manifest(make_compose(TARGET_IMAGE, infrastructure=SOURCE_IMAGE))
    )
    obj = json.loads(content)
    if mutation in {"sig", "key"}:
        obj[{"sig": "manifest_signature", "key": "key_signature"}[mutation]] = "0" * 128
        content = canonical_json(obj)
        pin = replace(pin, manifest_digest=digest_of(content))
    elif mutation == "bytes":
        content += b"\n"
    elif mutation == "duplicate":
        content = b'{"payload":{},' + content[1:]
        pin = replace(pin, manifest_digest=digest_of(content))
    else:
        pin = replace(pin, release_id="another-release")
    with pytest.raises(StagingError) as error:
        TRUST.verify(content, pin, now=NOW)
    assert error.value.reason is FailureReason.INVALID_PACKAGE


class Artifacts:
    def __init__(self) -> None:
        self.content = {}
        self.requests = []

    def get(self, url, _limit, *, cwd, deadline):
        self.requests.append(url)
        value = self.content[url]
        if isinstance(value, Exception):
            raise value
        return value


class Docker:
    def __init__(self) -> None:
        self.config_calls = []
        self.running = []
        self.pulls = []
        self.images = {SOURCE_IMAGE}
        self.pull_error = None
        self.bad_mcp = False
        self.binding_collision = False

    def info(self, _deadline):
        return {"DockerRootDir": "/var/lib/docker"}

    def compose_version(self, _deadline):
        return "5.7.1"

    def config(self, _path, project, profiles, env, _deadline):
        self.config_calls.append((profiles, env.copy()))
        names = (*CORE, "dvt-ai-mcp") if profiles else CORE
        services = {
            name: {
                "image": SOURCE_IMAGE if name in {"postgres", "valkey"} else TARGET_IMAGE,
                "networks": {"default": None},
            }
            for name in names
        }
        for name, src, dest in (
            ("postgres", "/data/pgdata", "/var/lib/postgresql/data"),
            ("valkey", "/data/valkeydata", "/data"),
            ("installation_manager", "", "/dvt-lib"),
        ):
            services[name]["volumes"] = [
                {"type": "bind", "source": env["DVT_LIB_DIR"] + src, "target": dest}
            ]
        services["installation_manager"]["ports"] = [
            {
                "host_ip": "127.0.0.1",
                "published": str(MANAGER_PORT),
                "target": 8000,
            }
        ]
        services["proxy"]["ports"] = [
            {"host_ip": "127.0.0.1", "published": str(APP_PORT), "target": 80}
        ]
        if self.binding_collision:
            services["ui"]["ports"] = services["proxy"]["ports"]
        services["gateway"]["environment"] = {
            "DVT_AI_MCP_ENABLED": env["DVT_AI_MCP_ENABLED"],
            "DVT_AI_MCP_INTERNAL_SECRET": env["DVT_AI_MCP_INTERNAL_SECRET"],
        }
        if "dvt-ai-mcp" in services:
            services["dvt-ai-mcp"]["environment"] = {
                "DVT_AI_MCP_INTERNAL_SECRET": ""
                if self.bad_mcp
                else env["DVT_AI_MCP_INTERNAL_SECRET"]
            }
        return {
            "name": project,
            "services": services,
            "networks": {"default": {"name": project + "_default"}},
        }

    def containers(self, _project, _deadline):
        return self.running

    def inspect_image(self, image_id, _deadline):
        assert image_id == "image ID"
        return {"RepoDigests": [SOURCE_IMAGE]}

    def network(self, _name, _deadline):
        return None

    def check_registries(self, _refs, _info):
        pass

    def local_image(self, ref, _platform, _deadline):
        return ref in self.images

    def pull(self, ref, _platform, _deadline):
        self.pulls.append(ref)
        if self.pull_error:
            raise self.pull_error
        self.images.add(ref)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = OperationStore(tmp_path / "state")
    identity = InstanceIdentity(
        uuid4(), "/var/lib/dvt", "dvt_beta_stage", "127.0.0.1", MANAGER_PORT, "http://example.test"
    )
    store.establish_identity(identity)
    configure = save_config(
        store,
        {
            "DVT_PUBLIC_URL": "http://example.test/;https://extra.example.test",
            "DVT_AI_MCP_ENABLED": "true",
            "COMPOSE_PROFILES": "ai-mcp",
            "DVT_EXTERNAL_PORT": str(APP_PORT),
            "DVT_AI_MCP_INTERNAL_SECRET": TEST_SECRET,
        },
    )
    downloader, docker = Artifacts(), Docker()
    service = VerifiedStaging(
        store,
        TRUST,
        downloader,
        docker,
        HostPaths(tmp_path, tmp_path, os_release=tmp_path / "os-release"),
        "1.23.0",
    )
    monkeypatch.setattr(verified_staging, "check_platform", lambda *_: "linux/amd64")
    monkeypatch.setattr(verified_staging, "require_writable", lambda *_: None)
    monkeypatch.setattr(verified_staging, "storage_budgets", lambda *_: [])
    monkeypatch.setattr(verified_staging, "check_filesystems", lambda *_: None)
    monkeypatch.setattr(staging_compose, "check_free_port", lambda *_: None)
    compose = make_compose(TARGET_IMAGE, infrastructure=SOURCE_IMAGE)
    manifest = make_manifest(compose)
    downloader.content.update(
        {ORIGIN + "/compose.yaml": compose, ORIGIN + "/bootstrap.sh": BOOTSTRAP}
    )
    pin, downloader.content[MANIFEST_URL] = sign_manifest(manifest)
    return service, configure, manifest, pin


def _admit(service, config_id, pin, kind=OperationKind.INSTALL):
    request = OperationRequest(kind, pin, config_id=config_id)
    return service.store.admit(request, idempotency_key=str(uuid4()))


def test_offline_intent_uses_shared_reservation_and_never_falls_back_to_network(setup):
    service, config_id, _, pin = setup
    store = service.store
    pending = store.admit(
        OperationRequest(OperationKind.INSTALL, pin, bundle_id=uuid4(), config_id=config_id),
        idempotency_key="offline-test",
    )
    with pytest.raises(OperationConflict) as blocked:
        _admit(service, config_id, pin)
    assert blocked.value.operation_id == pending.id
    with store.claim(pending.id), pytest.raises(OwnershipConflict):
        service.prepare(pending.id, MANIFEST_URL)
    with pytest.raises(StagingError, match="protected offline bundle is unavailable"):
        service.prepare(pending.id, MANIFEST_URL)
    assert service.downloader.requests == []
    assert service.docker.pulls == []
    assert store.get(pending.id).stage is OperationStage.PREPARING


def test_primary_origin_cannot_change_through_saved_config(setup):
    service, _, _, pin = setup
    config_id = save_config(
        service.store, {"DVT_PUBLIC_URL": "https://wrong.example.test;http://example.test"}
    )
    operation = _admit(service, config_id, pin)
    with pytest.raises(StagingError, match="primary public origin conflicts"):
        service.prepare(operation.id, MANIFEST_URL)
    assert service.docker.pulls == []


def _container(name, *, manager_host="127.0.0.1"):
    mounts = []
    if name in {"postgres", "valkey", "installation_manager"}:
        source, target = {
            "postgres": ("/var/lib/dvt/data/pgdata", "/var/lib/postgresql/data"),
            "valkey": ("/var/lib/dvt/data/valkeydata", "/data"),
            "installation_manager": ("/var/lib/dvt", "/dvt-lib"),
        }[name]
        mounts = [{"Type": "bind", "Source": source, "Destination": target, "RW": True}]
    port = {"installation_manager": (MANAGER_PORT, 8000), "proxy": (APP_PORT, 80)}.get(name)
    return {
        "Image": "image ID",
        "Config": {
            "Labels": {
                "com.docker.compose.service": name,
                "com.docker.compose.project": "dvt_beta_stage",
                "com.docker.compose.oneoff": "False",
            },
            "Env": [],
        },
        "State": {"Running": True},
        "HostConfig": {
            "PortBindings": {
                f"{port[1]}/tcp": [{"HostIp": manager_host, "HostPort": str(port[0])}],
            }
            if port
            else {}
        },
        "NetworkSettings": {"Networks": {"dvt_beta_stage_default": {}}},
        "Mounts": mounts,
    }


def test_prepare_and_continue_same_update_without_touching_working_config(
    setup, monkeypatch, tmp_path
):
    service, config_id, _, pin = setup
    monkeypatch.setenv("DVT_AI_MCP_INTERNAL_SECRET", "")
    monkeypatch.setenv("COMPOSE_FILE", "unexpected.yaml")
    runtime = set(CORE) - {"migrate"}
    service.docker.running = [_container(name) for name in sorted(runtime)]
    applied = ReleasePin("old", digest_of(b"older manifest"))
    observed = ObservedRelease(
        version="1.23.0", revision="0068", pin=applied, images=dict.fromkeys(runtime, SOURCE_IMAGE)
    )
    operation = _admit(service, config_id, pin, OperationKind.UPDATE)
    working = tmp_path / ".env"
    working.write_text("DVT_VERSION=1.23.0\n")
    service.docker.pull_error = StagingError(
        FailureReason.REGISTRY_UNAVAILABLE,
        "Temporary failure",
        "Retry later",
        retryable=True,
    )

    with pytest.raises(StagingError, match="Temporary"):
        service.prepare(operation.id, MANIFEST_URL, observed=observed, applied=applied)
    assert service.store.get(operation.id).stage is OperationStage.PREPARING
    assert (
        service.store.events(operation.id)[-1].checkpoint.outcome
        is CheckpointOutcome.RETRYABLE_ERROR
    )
    assert working.read_text() == "DVT_VERSION=1.23.0\n"
    service.docker.pull_error = None
    service.downloader.content[MANIFEST_URL] = b"new bytes after the operation was pinned"

    prepared = service.prepare(operation.id, MANIFEST_URL, observed=observed, applied=applied)
    assert service.downloader.requests.count(MANIFEST_URL) == 1
    assert prepared.pin == pin
    assert prepared.profiles == ("ai-mcp",)
    assert prepared.environment["DVT_AI_MCP_INTERNAL_SECRET"] == TEST_SECRET
    assert (
        prepared.environment["DVT_PUBLIC_URL"] == "http://example.test;https://extra.example.test"
    )
    assert "COMPOSE_FILE" not in prepared.environment
    assert TEST_SECRET not in repr(prepared)
    assert TEST_SECRET.encode() not in (prepared.compose_path.parent / "plan.json").read_bytes()
    state = service.store.get(operation.id)
    assert state.stage is OperationStage.PREPARED
    assert state.observation.source_digest == applied.manifest_digest
    assert state.observation.observed_digest == SOURCE_IMAGE.partition("@")[2]
    assert state.observation.target_digest == pin.manifest_digest
    assert state.observation.staging_id == operation.id
    assert working.read_text() == "DVT_VERSION=1.23.0\n"


@pytest.mark.parametrize(
    "failure",
    [
        "manifest",
        "compose",
        "bootstrap",
        "schema",
        "platform",
        "version",
        "mcp",
        "builder",
        "binding_collision",
    ],
)
def test_validation_failures_block_before_image_pulls(setup, monkeypatch, failure):
    service, config_id, manifest, pin = setup
    if failure == "manifest":
        service.downloader.content[MANIFEST_URL] += b"\n"
    elif failure in {"compose", "bootstrap"}:
        artifact = "compose.yaml" if failure == "compose" else "bootstrap.sh"
        service.downloader.content[f"{ORIGIN}/{artifact}"] += b"bad"
    elif failure == "platform":
        monkeypatch.setattr(verified_staging, "check_platform", lambda *_: "linux/arm64")
    elif failure == "version":
        service = replace(service, preparer_version="1.0.0")
    elif failure == "mcp":
        service.docker.bad_mcp = True
    elif failure == "binding_collision":
        service.docker.binding_collision = True
    elif failure == "builder":
        compose = (
            service.downloader.content[ORIGIN + "/compose.yaml"] + b"include: [outside.yaml]\n"
        )
        manifest = make_manifest(compose)
        pin, service.downloader.content[MANIFEST_URL] = sign_manifest(manifest)
        service.downloader.content[ORIGIN + "/compose.yaml"] = compose
    else:
        manifest["schema"]["initial_install"] = False
        pin, service.downloader.content[MANIFEST_URL] = sign_manifest(manifest)
    operation = _admit(service, config_id, pin)
    with pytest.raises(StagingError) as error:
        service.prepare(operation.id, MANIFEST_URL)
    assert TEST_SECRET not in str(error.value)
    assert not service.docker.pulls
    assert service.store.events(operation.id)[-1].checkpoint.outcome is CheckpointOutcome.BLOCKED


@pytest.mark.parametrize("case", ["matching", "binding", "unrelated"])
def test_first_install_only_accepts_matching_bootstrap(setup, case):
    service, config_id, _, pin = setup
    host = "127.0.0.2" if case == "binding" else "127.0.0.1"
    service.docker.running = [_container("installation_manager", manager_host=host)]
    if case == "unrelated":
        service.docker.running.append(_container("proxy"))
    operation = _admit(service, config_id, pin)
    if case == "matching":
        result = service.prepare(operation.id, MANIFEST_URL, bootstrap_image=SOURCE_IMAGE)
        assert result.recreate == ("installation_manager",)
    else:
        with pytest.raises(StagingError, match=r"running service|established source"):
            service.prepare(operation.id, MANIFEST_URL, bootstrap_image=SOURCE_IMAGE)
        assert service.docker.pulls == []


@pytest.mark.parametrize("change", ["port", "volume", "credentials", "image", "network"])
def test_infrastructure_changes_block_before_pull(setup, change):
    service, config_id, _, pin = setup
    runtime = set(CORE) - {"migrate"}
    service.docker.running = [_container(name) for name in sorted(runtime)]
    postgres = next(
        c
        for c in service.docker.running
        if c["Config"]["Labels"]["com.docker.compose.service"] == "postgres"
    )
    if change == "port":
        postgres["HostConfig"]["PortBindings"] = {
            "5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5432"}]
        }
    elif change == "volume":
        postgres["Mounts"][0]["Source"] += "_changed"
    elif change == "credentials":
        postgres["Config"]["Env"].append("POSTGRES_PASSWORD=source-private-password")
    elif change == "network":
        postgres["NetworkSettings"]["Networks"] = {"unexpected": {}}
    else:
        postgres["Image"] = TARGET_IMAGE
        service.docker.inspect_image = lambda ref, deadline: {
            "RepoDigests": [ref if ref == TARGET_IMAGE else SOURCE_IMAGE]
        }
    observed = ObservedRelease(
        version="1.23.0", revision="0068", pin=None, images=dict.fromkeys(runtime, SOURCE_IMAGE)
    )
    operation = _admit(service, config_id, pin, OperationKind.UPDATE)
    with pytest.raises(StagingError) as error:
        service.prepare(operation.id, MANIFEST_URL, observed=observed)
    assert error.value.reason is FailureReason.INCOMPATIBLE_RELEASE
    assert "source-private-password" not in str(error.value)
    assert service.docker.pulls == []


def test_an_older_signed_release_requires_recovery_before_pulling(setup):
    service, configure, manifest, _ = setup
    manifest["version"] = "1.22.0"
    manifest["release_id"] = "older-signed-release"
    manifest["schema"]["from_releases"][0]["version"] = "1.21.0"
    newer = ReleasePin("newer", digest_of(b"newer source"))
    pin, service.downloader.content[MANIFEST_URL] = sign_manifest(manifest)
    observed = ObservedRelease(
        version="1.23.0", revision="0068", pin=newer,
        images=dict.fromkeys(set(CORE) - {"migrate"}, SOURCE_IMAGE),
    )
    operation = _admit(service, configure, pin, OperationKind.UPDATE)

    with pytest.raises(StagingError, match="earlier release requires a verified recovery plan"):
        service.prepare(operation.id, MANIFEST_URL, observed=observed, applied=newer)

    assert service.docker.pulls == []
    assert service.store.get(operation.id).stage is OperationStage.PREPARING
    assert service.store.first_failure(operation.id).checkpoint.reason is (
        FailureReason.INCOMPATIBLE_RELEASE
    )


@pytest.mark.parametrize("foreign_readonly_bind", [False, True])
def test_bridge_files_do_not_become_persistent_storage_budgets(
    setup, tmp_path, monkeypatch, foreign_readonly_bind,
):
    service, _, _, _ = setup
    identity = service.store.identity()
    bridge_binds = operator_binds(str(tmp_path))
    for source in bridge_binds.values():
        credential = Path(source)
        credential.parent.mkdir(exist_ok=True)
        credential.write_text("test-only fixture")
    monkeypatch.setattr(staging_compose, "operator_binds", lambda _data: bridge_binds)

    env = {
        "DVT_LIB_DIR": identity.data_dir,
        "DVT_EXTERNAL_PORT": str(APP_PORT),
        "DVT_AI_MCP_ENABLED": "false",
        "DVT_AI_MCP_INTERNAL_SECRET": TEST_SECRET,
    }
    roles = set(CORE) - {"migrate"}
    model = service.docker.config(None, identity.compose_project, (), env, None)
    service.docker.running = [_container(name) for name in sorted(roles)]
    gateway = next(
        container for container in service.docker.running
        if container["Config"]["Labels"]["com.docker.compose.service"] == "gateway"
    )
    gateway["Mounts"] = [
        {"Type": "bind", "Source": source, "Destination": target, "RW": False}
        for target, source in bridge_binds.items()
    ]
    if foreign_readonly_bind:
        gateway["Mounts"].append({
            "Type": "bind", "Source": str(tmp_path / "foreign"),
            "Destination": "/run/foreign", "RW": False,
        })
    observed = ObservedRelease(
        version="1.23.0", revision="0068", pin=None, images=dict.fromkeys(roles, SOURCE_IMAGE),
    )
    if foreign_readonly_bind:
        with pytest.raises(StagingError, match="Candidate changes data mounts"):
            staging_compose.compare_project(model, identity, env, service.docker, observed, None)
        return

    plan = staging_compose.compare_project(model, identity, env, service.docker, observed, None)
    # Map the mock runtime's database directories to genuine directories. The injected mounts
    # already point to real files, so an erroneous inclusion must fail the directory check.
    working_paths = {}
    for name in ("pgdata", "valkeydata"):
        directory = tmp_path / name
        directory.mkdir()
        working_paths[name] = directory
    if not hasattr(staging_host.os, "statvfs"):
        monkeypatch.setattr(staging_host.os, "statvfs", lambda _: SimpleNamespace(
            f_bavail=1024, f_frsize=4096, f_favail=1024,
        ), raising=False)
    check_filesystems([
        FilesystemBudget("persistent data", working_paths.get(path.name, path), 1, 1)
        for path in plan.persistent_paths
    ])
    assert {path.name for path in plan.persistent_paths} == {"pgdata", "valkeydata"}
