from __future__ import annotations

import subprocess
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.installation_manager import candidate_api, host_bootstrap
from services.installation_manager.candidate_api import create_app
from services.installation_manager.candidate_auth import CandidateAuth
from services.installation_manager.candidate_executor import execute
from services.installation_manager.domain.operation_state import (
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
    for url in ("/api/config", "/api/secrets", "/api/operations", "/api/operations/active"):
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
    assert client.post("/api/update", json={}, headers=CSRF).status_code == 410
    assert client.post("/api/operations", json={}).status_code == 403
    assert client.get("/api/operations/active").json() is None

    # A replacement web process imports the same private authorization material.
    replacement = TestClient(
        create_app(config, store, None), base_url=ORIGIN, cookies=client.cookies
    )
    assert replacement.get("/api/operations").json() == []


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
