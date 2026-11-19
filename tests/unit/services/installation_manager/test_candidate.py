from __future__ import annotations

import json
import stat
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.data.installation_manager.verified_staging.fixtures import (
    TARGET_IMAGE,
    make_compose,
    make_manifest,
    sign_manifest,
)

from services.installation_manager import candidate_api, catalog_api, host_bootstrap, operator_api
from services.installation_manager.candidate_api import create_app
from services.installation_manager.candidate_auth import CandidateAuth
from services.installation_manager.candidate_executor import execute
from services.installation_manager.domain.operation_state import (
    ArtifactKind,
    Checkpoint,
    CheckpointOutcome,
    InstanceIdentity,
    InvalidTransition,
    Observation,
    OperationKind,
    OperationRequest,
    OperationStage,
    ReleasePin,
)
from services.installation_manager.infrastructure.operation_store import OperationStore
from services.installation_manager.infrastructure.operator_wiring import wire_gateway
from services.installation_manager.infrastructure.staging_artifacts import (
    artifact_directory,
    write_artifact,
)

ORIGIN = "https://localhost:8888"
CSRF = {"Origin": ORIGIN, "X-DVT-CSRF": "1"}
MACHINE = {"Authorization": "Bearer fixture-token"}


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    identifier = uuid4()
    data_dir = f"/var/lib/dvt-{identifier}" if tmp_path.drive else str(tmp_path)
    control = tmp_path / host_bootstrap.CONTROL
    control.mkdir(mode=0o700)
    for name, contents in (("session-key", b"k" * 32), ("machine-token", b"fixture-token")):
        host_bootstrap.atomic_write(control / name, contents)
    config = {
        "instance": str(identifier),
        "data": str(tmp_path),
        "project": "fixture",
        "address": "127.0.0.1",
        "port": 8888,
        "public_url": "http://fixture.invalid",
        "manager": f"fixture.invalid/dvt@sha256:{'1' * 64}",
        "candidate": f"fixture.invalid/dvt@sha256:{'2' * 64}",
        "executor": f"fixture.invalid/dvt@sha256:{'3' * 64}",
    }
    store = OperationStore.for_host(tmp_path)
    store.establish_identity(
        InstanceIdentity(
            identifier,
            data_dir,
            config["project"],
            config["address"],
            config["port"],
            config["public_url"],
        )
    )
    dispatched = []

    def launch(_config, operation_id):
        operation = store.active()
        assert str(operation.id) == operation_id
        dispatched.append(operation.id)

    monkeypatch.setattr(candidate_api, "launch", launch)
    return config, store, dispatched


def test_anonymous_api_and_bad_browser_origin_cannot_control_candidate(candidate):
    config, store, dispatched = candidate
    client = TestClient(create_app(config, store, None), base_url=ORIGIN)
    auth = CandidateAuth(config)
    code = auth.issue_pairing()
    assert client.get("/health").json() == {"status": "ok"}
    for url in (
        "/api/config", "/api/secrets", "/api/operations", "/api/operations/active", "/api/releases",
    ):
        assert client.get(url).status_code == 401
    assert client.get("/health", headers={"Host": "evil.example:8888"}).status_code == 421
    assert client.post("/api/session", json={"code": code}).status_code == 403
    assert (
        client.post(
            "/api/session",
            json={"code": code},
            headers={**CSRF, "Origin": "https://evil.example:8888"},
        ).status_code
        == 403
    )
    assert client.get("/api/operations", headers={**MACHINE, "Origin": ORIGIN}).status_code == 401
    assert not dispatched

    paired = client.post("/api/session", json={"code": code}, headers=CSRF)
    assert paired.status_code == 200
    assert all(
        flag in paired.headers["set-cookie"] for flag in ("Secure", "HttpOnly", "SameSite=strict")
    )
    assert client.post("/api/session", json={"code": code}, headers=CSRF).status_code == 401
    assert client.get("/api/releases").status_code == 503
    assert client.get("/health").json() == {"status": "ok"}
    assert client.post("/api/releases/selection", json={}).status_code == 403
    assert client.post("/api/update", json={}, headers=CSRF).status_code == 410
    assert client.post("/api/operations", json={}).status_code == 403
    assert client.get("/api/operations/active").json() is None

    # A replacement web process imports the same private authorization material.
    replacement = TestClient(
        create_app(config, store, None), base_url=ORIGIN, cookies=client.cookies
    )
    assert replacement.get("/api/operations").json() == []


def test_initial_release_pin_limits_first_install_to_the_saved_version_and_digest(
    candidate, tmp_path, monkeypatch
):
    config, store, _ = candidate
    launch_config = tmp_path / host_bootstrap.CONTROL / "launch-host.conf"
    metadata = b"project\nmanager\n/docker\n\n8888\n"
    host_bootstrap.atomic_write(launch_config, metadata)
    client = TestClient(create_app(config, store, None), base_url=ORIGIN)
    status = client.get("/api/operator/settings", headers=MACHINE).json()
    assert status["instance_id"] == config["instance"]
    assert status["initial_release_version"] is None

    version = "1.24.0-rc8"
    digest = "sha256:" + "a" * 64
    selected = SimpleNamespace(version=version, channel="rc", manifest_digest=digest)
    newer = SimpleNamespace(version="1.24.0-rc9", channel="rc", manifest_digest="sha256:" + "b" * 64)
    stable = SimpleNamespace(version="1.24.0", channel="stable", manifest_digest="sha256:" + "d" * 64)
    releases = [selected, newer, stable]
    catalog = SimpleNamespace(
        verify=True,
        refresh=lambda: SimpleNamespace(releases=releases, fetched_at=None, error=None),
        paths=lambda *_args, **_kwargs: {row.version: [row] for row in releases},
        select=lambda entry, *_args, **_kwargs: entry,
    )
    monkeypatch.setattr(catalog_api, "catalog_client", lambda _: catalog)
    monkeypatch.setattr(catalog_api, "observe_source", lambda *_: None)
    combined = client.get("/api/releases?channel=all", headers=MACHINE).json()
    assert [row["version"] for row in combined["releases"]] == [stable.version, newer.version, version]
    assert combined["recommended_stable"]["version"] == stable.version
    assert combined["first_steps"][version]["channel"] == "rc"
    assert [row["version"] for row in client.get(
        "/api/releases", headers=MACHINE,
    ).json()["releases"]] == [stable.version]

    host_bootstrap.atomic_write(launch_config, metadata + f"{version} {digest}\n".encode())
    assert client.get("/api/operator/settings", headers=MACHINE).json()["initial_release_version"] == version
    for channel in ("rc", "all"):
        listing = client.get(f"/api/releases?channel={channel}", headers=MACHINE).json()
        assert [row["version"] for row in listing["releases"]] == [version]
        assert listing["recommended_stable"] is None

    def select(row):
        return client.post("/api/releases/selection", headers=MACHINE, json={
            "version": row.version, "manifest_digest": row.manifest_digest, "confirm_rc": True,
        })

    assert select(selected).status_code == 200
    assert select(newer).status_code == 409
    selected.manifest_digest = "sha256:" + "c" * 64
    assert select(selected).status_code == 409


def test_expired_pairing_and_validation_errors_do_not_reveal_codes(candidate, monkeypatch):
    config, store, _dispatched = candidate
    auth = CandidateAuth(config)
    code = auth.issue_pairing()
    monkeypatch.setattr("services.installation_manager.candidate_auth.PAIR_TTL", -1)
    expired_code = auth.issue_pairing()
    client = TestClient(create_app(config, store, None), base_url=ORIGIN)
    assert client.post("/api/session", json={"code": expired_code}, headers=CSRF).status_code == 401
    malformed = code + "-bad"
    response = client.post("/api/session", json={"code": malformed}, headers=CSRF)
    assert response.status_code == 422
    assert malformed not in response.text


def test_operation_is_persisted_before_dispatch_and_idempotent_across_web_recreation(candidate):
    config, store, dispatched = candidate
    first = TestClient(create_app(config, store, None), base_url=ORIGIN)
    pin = first.get("/api/operations/candidate", headers=MACHINE).json()
    request = {"kind": "manager_recovery", "release": pin}
    selected = first.post(
        "/api/operations", headers={**MACHINE, "Idempotency-Key": "once"}, json=request
    )
    assert selected.status_code == 202
    operation = selected.json()["operation"]
    operation_id = operation["id"]
    assert operation["instance_id"] == config["instance"]
    assert operation["stage"] == "admitted"
    assert len(dispatched) == 1

    second = TestClient(create_app(config, store, None), base_url=ORIGIN)
    assert second.get(f"/api/operations/{operation_id}", headers=MACHINE).json() == selected.json()
    assert second.get("/api/operations/active", headers=MACHINE).json() == selected.json()
    assert second.get("/api/operations", headers=MACHINE).json() == [selected.json()]
    events = second.get(f"/api/operations/{operation_id}/events", headers=MACHINE).json()
    assert [event["kind"] for event in events] == ["admitted"]

    conflict = second.post(
        "/api/operations", headers={**MACHINE, "Idempotency-Key": "different"}, json=request
    )
    assert conflict.status_code == 409
    assert conflict.headers["location"] == f"/api/operations/{operation_id}"
    assert conflict.json() == {"detail": {"operation_id": operation_id}}
    replay = second.post(
        "/api/operations", headers={**MACHINE, "Idempotency-Key": "once"}, json=request
    )
    assert replay.json()["operation"]["id"] == operation_id
    assert len(dispatched) == 2 and dispatched[0] == dispatched[1]

    changed = {**request, "release": {**pin, "manifest_digest": "sha256:" + "b" * 64}}
    response = second.post(
        "/api/operations", headers={**MACHINE, "Idempotency-Key": "once"}, json=changed
    )
    assert response.status_code == 422
    client_injected = {**request, "docker_root": "/etc"}
    response = second.post(
        "/api/operations", headers={**MACHINE, "Idempotency-Key": "once"}, json=client_injected
    )
    assert response.status_code == 422


def test_launch_failure_leaves_same_operation_for_boot_or_explicit_resume(candidate, monkeypatch):
    config, store, _dispatched = candidate
    client = TestClient(create_app(config, store, None), base_url=ORIGIN)
    pin = client.get("/api/operations/candidate", headers=MACHINE).json()

    def unavailable(*_):
        raise subprocess.CalledProcessError(1, "docker")

    monkeypatch.setattr(candidate_api, "launch", unavailable)
    response = client.post(
        "/api/operations",
        headers={**MACHINE, "Idempotency-Key": "later"},
        json={"kind": "manager_recovery", "release": pin},
    )
    assert response.status_code == 202
    assert response.json()["operation"]["id"] == str(store.active().id)
    assert response.json()["actions"] == ["resume"]


@pytest.mark.parametrize("interrupted", [False, True])
def test_candidate_executor_returns_to_previous_image_after_http_failure(
    candidate, monkeypatch, interrupted
):
    config, store, _dispatched = candidate
    release = ReleasePin(*host_bootstrap.candidate(config))
    op = store.admit(
        OperationRequest(OperationKind.MANAGER_RECOVERY, release), idempotency_key="fallback"
    )
    path = "services.installation_manager.candidate_executor"
    runtime = {"image": config["manager"], "interrupt": interrupted, "target_probes": 0}
    monkeypatch.setattr(path + ".check_image", lambda image: image)
    monkeypatch.setattr(path + "._check_host", lambda *_: None)
    monkeypatch.setattr(path + ".init_container", lambda *_: "1")
    monkeypatch.setattr(
        path + "._project_manager",
        lambda *_: {"State": {"Running": True}, "Image": runtime["image"]},
    )

    def apply(_config, image, _path):
        assert store.active().stage is OperationStage.RECOVERING
        assert store.active().last_owner
        if image == config["manager"] and runtime["interrupt"]:
            runtime["interrupt"] = False
            raise KeyboardInterrupt
        runtime["image"] = image

    def probe(_config, _store, operation_id, claim_id):
        assert operation_id == op.id
        assert store.active().last_owner.claim_id == claim_id
        if runtime["image"] == config["candidate"]:
            runtime["target_probes"] += 1
            raise OSError("candidate HTTPS unavailable")

    monkeypatch.setattr(path + ".apply_manager", apply)
    monkeypatch.setattr(path + "._probe", probe)
    if interrupted:
        with pytest.raises(KeyboardInterrupt):
            execute(config, store, op.id)
        assert store.active().stage is OperationStage.RECOVERING
    execute(config, store, op.id)
    operation = store.get(op.id)
    assert runtime["target_probes"] == 1
    assert operation.stage is OperationStage.CANCELLED
    assert operation.observation.observed_digest == release_digest(config["manager"])
    assert operation.observation.target_digest == release_digest(config["candidate"])
    assert any(
        event.checkpoint and event.checkpoint.outcome is CheckpointOutcome.BLOCKED
        for event in store.events(op.id)
    )


def release_digest(reference):
    return reference.split("@")[1]


def test_cannot_cancel_data_recovery_using_manager_fallback(candidate):
    config, store, _dispatched = candidate
    release = ReleasePin(*host_bootstrap.candidate(config))
    op = store.admit(OperationRequest(OperationKind.RESTORE, release), idempotency_key="data")
    digest = release_digest(config["manager"])
    with store.claim(op.id) as owner:
        owner.checkpoint(Checkpoint(OperationStage.PREPARING))
        owner.checkpoint(
            Checkpoint(OperationStage.PREPARED, observation=Observation(source_digest=digest))
        )
        owner.checkpoint(Checkpoint(OperationStage.RECOVERING))
        with pytest.raises(InvalidTransition):
            owner.checkpoint(
                Checkpoint(
                    OperationStage.CANCELLED,
                    CheckpointOutcome.VERIFIED,
                    observation=Observation(observed_digest=digest),
                )
            )


def test_noninteractive_package_preparation_requires_consent(monkeypatch):
    monkeypatch.setattr(host_bootstrap, "docker_ready", lambda: False)

    def unexpected(*_, **_kwargs):
        pytest.fail("No package preparation commands are authorized")

    monkeypatch.setattr(host_bootstrap, "command", unexpected)
    with pytest.raises(ValueError, match="explicit permission"):
        host_bootstrap.install_docker(allowed=False, interactive=False)


def test_diagnostics_is_authorized_paginated_and_preserves_failure(candidate):
    from services.installation_manager.application.recovery import Action, import_source_failure
    from services.installation_manager.domain.operation_state import ArtifactKind, FailureReason
    from services.installation_manager.infrastructure.staging_artifacts import (
        artifact_directory,
        write_artifact,
    )

    config, store, dispatched = candidate
    operation = store.admit(
        OperationRequest(OperationKind.INSTALL, ReleasePin("fixture", "sha256:" + "a" * 64)),
        idempotency_key="diagnostics-fixture",
    )
    with store.claim(operation.id) as owner:
        owner.checkpoint(Checkpoint(OperationStage.PREPARING))
        owner.checkpoint(Checkpoint(OperationStage.PREPARED))
        owner.checkpoint(Checkpoint(OperationStage.MIGRATING))
        owner.checkpoint(Checkpoint(
            OperationStage.MIGRATING, CheckpointOutcome.BLOCKED,
            FailureReason.INCOMPATIBLE_SCHEMA,
        ))
    staging = artifact_directory(store, ArtifactKind.STAGING, operation.id)
    write_artifact(staging / "support-observation.json", b'{"compose_version":"fixture-token"}')
    url = f"/api/operations/{operation.id}"
    client = TestClient(create_app(config, store, None), base_url=ORIGIN)
    assert client.get(url + "/diagnostics").status_code == 401
    response = client.get(url + "/diagnostics", headers=MACHINE)
    assert response.status_code == 200
    assert "fixture-token" not in response.text
    assert response.json()["observation"] is None
    assert response.json()["snapshot"]["actions"] == []
    imported = import_source_failure(response.content, store.get(operation.id))
    assert imported.operation_id == operation.id
    assert imported.reason is FailureReason.INCOMPATIBLE_SCHEMA
    assert [event["checkpoint"]["reason"] for event in response.json()["events"] if
            event["checkpoint"] and event["checkpoint"]["reason"]] == ["incompatible_schema"]
    assert client.get(url + "/diagnostics?limit=101", headers=MACHINE).status_code == 422
    assert client.get(f"/api/operations/{uuid4()}/diagnostics", headers=MACHINE).status_code == 404
    assert client.post(url + f"/actions/{Action.RESUME}", headers=MACHINE).status_code == 409
    assert not dispatched


def test_operator_install_admission_is_single_and_replay_survives_web_restart(candidate, monkeypatch):
    config, store, dispatched = candidate
    auth = CandidateAuth(config)
    selected = SimpleNamespace(pin=ReleasePin("stable", "sha256:" + "1" * 64))
    monkeypatch.setattr(operator_api, "select_release", lambda *_: (selected, None))
    client = TestClient(create_app(config, store, None), base_url=ORIGIN)
    data = {"kind": "install", "version": "1.2.3", "manifest_digest": selected.pin.manifest_digest}
    path = "/api/operator/operations"
    key = {"Idempotency-Key": "install-request"}

    assert client.post(path, json=data, headers={**CSRF, **key}).status_code == 401
    assert client.post("/api/session", json={"code": auth.issue_pairing()}, headers=CSRF).status_code == 200
    assert client.post(path, json=data, headers=key).status_code == 403
    assert client.post(path, json=data, headers={
        **key, "Authorization": f"Bearer {auth.gateway_token}",
    }).status_code == 403

    response = client.post(path, json=data, headers={**CSRF, **key})
    assert response.status_code == 202
    operation = store.active()
    assert dispatched == [operation.id]
    assert response.json()["id"] == str(operation.id)
    assert operation.request.app_port == 80
    assert operation.request.task_workers_count == 1

    replacement = TestClient(create_app(config, store, None), base_url=ORIGIN, cookies=client.cookies)
    replay = replacement.post(path, json=data, headers={**CSRF, **key})
    assert replay.status_code == 202 and replay.json()["id"] == str(operation.id)
    changed = replacement.post(path, json={**data, "task_workers_count": 2}, headers={**CSRF, **key})
    assert changed.status_code == 409 and changed.json()["detail"]["operation_id"] == str(operation.id)
    assert replacement.get(path + "/" + str(operation.id), headers={
        "Authorization": f"Bearer {auth.gateway_token}",
    }).status_code == 404
    assert store.history() == [operation]


def test_setup_pairing_is_separate_ready_only_single_use_and_absent_from_diagnostics(candidate):
    config, store, _ = candidate
    auth = CandidateAuth(config)
    client = TestClient(create_app(config, store, None), base_url=ORIGIN)
    browser_code = auth.issue_pairing()
    client.post("/api/session", json={"code": browser_code}, headers=CSRF).raise_for_status()
    bridge = {"Authorization": f"Bearer {auth.gateway_token}"}
    operation = store.admit(
        OperationRequest(OperationKind.INSTALL, ReleasePin("stable", "sha256:" + "2" * 64)),
        idempotency_key="first-install",
    )
    path = f"/api/operator/setup/{operation.id}"
    assert client.post(path + "/pairing", headers=CSRF, json={}).status_code == 409
    with store.claim(operation.id) as owner:
        for stage in (
            OperationStage.PREPARING, OperationStage.PREPARED, OperationStage.MIGRATING,
            OperationStage.APPLYING, OperationStage.VERIFYING, OperationStage.RESUMING,
        ):
            owner.checkpoint(Checkpoint(stage, CheckpointOutcome.VERIFIED))
        owner.checkpoint(Checkpoint(OperationStage.SUCCEEDED, CheckpointOutcome.VERIFIED))
    current = auth.directory / "current-release.json"
    host_bootstrap.atomic_write(current, json.dumps({"operation": str(operation.id)}).encode())

    assert client.get("/api/operator/settings").json()["setup_required"]
    assert client.post(path + "/pairing", headers=bridge, json={}).status_code == 401
    code = client.post(path + "/pairing", headers=CSRF, json={}).json()["code"]
    assert code != browser_code
    assert client.post(path + "/exchange", headers=CSRF, json={"code": code}).status_code == 401
    assert client.post(path + "/exchange", headers=bridge, json={"code": browser_code}).status_code == 401
    assert client.post(path + "/exchange", headers=bridge, json={"code": code}).status_code == 200
    assert client.post(path + "/exchange", headers=bridge, json={"code": code}).status_code == 401
    response = client.get(f"/api/operator/operations/{operation.id}/diagnostics")
    assert response.status_code == 200
    assert all(value not in response.text for value in (code, browser_code, auth.gateway_token))
    client.post(path + "/complete", headers=bridge).raise_for_status()
    assert not client.get("/api/operator/settings").json()["setup_required"]
    assert client.post(path + "/pairing", headers=CSRF, json={}).status_code == 409


def test_update_requires_explicit_apply_from_the_same_prepared_operation(candidate, monkeypatch):
    config, store, _ = candidate
    operation = store.admit(
        OperationRequest(OperationKind.UPDATE, ReleasePin("target", "sha256:" + "2" * 64)),
        idempotency_key="fixed-target",
    )
    with store.claim(operation.id) as owner:
        owner.checkpoint(Checkpoint(OperationStage.PREPARING))
        owner.checkpoint(Checkpoint(OperationStage.PREPARED))
    launched = []
    monkeypatch.setattr(candidate_api, "launch", lambda _, id_, action: launched.append((id_, action)))
    client = TestClient(create_app(config, store, None), base_url=ORIGIN)
    bridge = {"Authorization": f"Bearer {CandidateAuth(config).gateway_token}"}
    path = f"/api/operator/operations/{operation.id}"
    assert "apply" in client.get(path, headers=bridge).json()["actions"]
    summary = "/api/operator/update-summary"
    assert client.get(summary).status_code == 401
    assert client.get(summary, headers=bridge).json() is None
    assert client.post(path + "/actions/apply", headers=bridge, json={}).status_code == 422
    assert client.post(path + "/actions/return_to_source", headers=bridge, json={
        "confirm": True,
    }).status_code == 409
    assert launched == []
    response = client.post(path + "/actions/apply", headers=bridge, json={"confirm": True})
    assert response.status_code == 202
    assert response.json()["id"] == str(operation.id)
    assert launched == [(str(operation.id), "candidate-maintenance")]
    with store.claim(operation.id) as owner:
        owner.checkpoint(Checkpoint(OperationStage.MAINTENANCE))
    status = client.get(summary, headers=bridge).json()
    assert (status["id"], status["state"]) == (str(operation.id), "running")


def test_operator_plan_reports_staged_transition_and_excludes_private_metadata(candidate):
    config, store, _ = candidate
    release = make_manifest(make_compose(TARGET_IMAGE))
    pin, signed = sign_manifest(release)
    operation = store.admit(OperationRequest(OperationKind.UPDATE, pin), idempotency_key="plan")
    with store.claim(operation.id) as owner:
        owner.checkpoint(Checkpoint(OperationStage.PREPARING))
        owner.checkpoint(Checkpoint(OperationStage.PREPARED, observation=Observation(
            staging_id=operation.id, source_revision="0068", target_revision="0069",
        )))
    artifacts = artifact_directory(store, ArtifactKind.STAGING, operation.id)
    write_artifact(artifacts / "manifest.json", signed)
    write_artifact(artifacts / "plan.json", json.dumps({
        "platform": "linux/amd64",
        "profiles": [],
        "services": {"gateway": TARGET_IMAGE},
        "observed_version": "1.23.0",
        "observed_revision": "0068",
        "target_revision": "0069",
        "transition": release["schema"]["from_releases"][0],
        "add": [], "recreate": ["gateway"], "retire": [],
        "private_test_field": "protected-never-returns",
    }).encode())
    client = TestClient(create_app(config, store, None), base_url=ORIGIN)
    bridge = {"Authorization": f"Bearer {CandidateAuth(config).gateway_token}"}
    response = client.get(f"/api/operator/operations/{operation.id}", headers=bridge)
    assert response.status_code == 200
    result = response.json()
    plan = result["plan"]
    assert result["version"] == plan["target_version"] == "1.24.0"
    assert (plan["source_version"], plan["migration"], plan["rollback"]) == (
        "1.23.0", "from_revision", "restore_backup",
    )
    assert plan["pull_and_unpack_bytes"] == 12 * 1024**2
    assert "protected-never-returns" not in response.text


@pytest.mark.parametrize("direct", [False, True])
def test_gateway_gets_only_read_only_bridge_files_and_manager_network(candidate, direct):
    config, _, _ = candidate
    config["manager_http"] = direct
    auth = CandidateAuth(config)
    if not direct:
        host_bootstrap.atomic_write(auth.directory / "ca.pem", b"test ca")
    services = {
        "gateway": {"networks": {"application": None}, "volumes": [], "environment": {}},
        "installation_manager": {"networks": {"default": None}},
    }
    wire_gateway(services, config)
    result = services["gateway"]
    assert set(result["networks"]) == {"application", "default"}
    assert set(result["environment"].values()) == {("http://fixture.invalid:8888" if direct else ORIGIN)}
    source_names = {mount["source"].replace("\\", "/").rsplit("/", 1)[1] for mount in result["volumes"]}
    assert source_names == ({"gateway-token"} if direct else {"gateway-token", "ca.pem"})
    assert all(mount["read_only"] for mount in result["volumes"])
    scoped_token = (auth.directory / "gateway-token").read_text()
    assert scoped_token == auth.gateway_token and scoped_token != auth.machine



@pytest.mark.parametrize(
    "case", ["empty", "prepared", "update", "offline", "different_id", "occupied", "unapproved", "applied"],
)
def test_resume_restores_only_an_approved_manager_for_empty_early_online_install(
    tmp_path, monkeypatch, case,
):
    operation_id = str(uuid4())
    config_id = str(uuid4())
    config = {
        "data": str(tmp_path), "project": "test", "release_catalog": {"origin": "https://test.dev"},
        "manager": TARGET_IMAGE, "candidate": TARGET_IMAGE,
    }
    control = tmp_path / host_bootstrap.CONTROL
    control.mkdir()
    if case == "applied":
        (control / "current-release.json").write_text("{}", encoding="utf-8")
    marker = control / "current-manager"
    marker.write_text(TARGET_IMAGE if case != "unapproved" else "unapproved", encoding="utf-8")
    operator = tmp_path / host_bootstrap.STATE / "artifacts" / "config" / config_id / "operator.json"
    operator.parent.mkdir(parents=True)
    operator.write_text("{}", encoding="utf-8")
    active = (
        str(uuid4()) if case == "different_id" else operation_id,
        "prepared" if case == "prepared" else "preparing",
        json.dumps({
            "kind": "update" if case == "update" else "install",
            "bundle_id": str(uuid4()) if case == "offline" else None,
            "config_id": config_id,
        }),
    )
    lstat = type(marker).lstat
    monkeypatch.setattr(
        type(marker), "lstat",
        lambda path: SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o600)
        if path == marker else lstat(path),
    )
    monkeypatch.setattr(host_bootstrap, "active_operation", lambda _: active)
    monkeypatch.setattr(
        host_bootstrap, "docker",
        lambda *args: SimpleNamespace(stdout="unrelated" if case == "occupied" else ""),
    )
    checked = []
    applied = []
    monkeypatch.setattr(host_bootstrap, "check_image", checked.append)
    monkeypatch.setattr(host_bootstrap, "apply_manager", lambda *args: applied.append(args))

    if case == "unapproved":
        with pytest.raises(ValueError, match="differs from the approved"):
            host_bootstrap.restore_initial_manager(config, operation_id)
    else:
        host_bootstrap.restore_initial_manager(config, operation_id)

    if case == "empty":
        assert checked == [TARGET_IMAGE]
        assert applied == [(config, TARGET_IMAGE, control / "bootstrap.compose.yaml")]
    else:
        assert checked == applied == []
