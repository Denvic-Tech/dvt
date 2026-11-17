from uuid import uuid4

from services.installation_manager.application import legacy_adopt
from services.installation_manager.domain.operation_state import (
    ArtifactKind,
    InstanceIdentity,
    OperationKind,
    OperationRequest,
    OperationStage,
    ReleasePin,
)
from services.installation_manager.domain.release_manifest import canonical_json, digest_of
from services.installation_manager.infrastructure.operation_store import OperationStore
from services.installation_manager.infrastructure.staging_artifacts import (
    artifact_directory,
    write_artifact,
)


def test_legacy_manager_adoption_does_not_commit_working_files_before_verified_handoff(
    tmp_path, monkeypatch,
):
    project = "legacy"
    identity = InstanceIdentity(uuid4(), "/fixture", project, "127.0.0.1", 18901, "http://fixture")
    store = OperationStore.for_host(tmp_path)
    store.establish_identity(identity)
    approved = ReleasePin("original", "sha256:" + "a" * 64)
    operation = store.admit(
        OperationRequest(OperationKind.MANAGER_RECOVERY, approved), idempotency_key="adopt",
    )
    new, old, gateway = (f"fixture.invalid/dvt@sha256:{value * 64}" for value in "bcd")
    config = {
        "data": str(tmp_path), "project": project, "manager": new,
        "instance": str(identity.instance_id),
    }
    working = tmp_path / "docker-compose.yaml"
    working.write_bytes(b"legacy-runtime")
    environment = tmp_path / ".env"
    environment.write_bytes(b"existing-values")
    (tmp_path / ".bootstrap").mkdir()
    obs = artifact_directory(store, ArtifactKind.STAGING, operation.id)
    write_artifact(obs / "legacy-working.compose.yaml", b"legacy-runtime-with-verified-manager")
    write_artifact(obs / "legacy-fallback.compose.yaml", b"legacy-fallback")
    write_artifact(obs / "legacy-env", environment.read_bytes())
    applications = {"postgres": [{"Id": "original-postgres"}], "gateway": [{"Id": "original-gateway"}]}
    write_artifact(obs / legacy_adopt.PLAN, canonical_json({
        "fallback": old,
        "source": {
            "instance": str(identity.instance_id),
            "operation": str(operation.id),
            "manifest_digest": approved.manifest_digest,
            "revision": "0070",
            "database": "123:42",
            "images": {"installation_manager": new, "gateway": gateway},
            "compose_digest": digest_of((obs / "legacy-working.compose.yaml").read_bytes()),
            "config_digest": digest_of(environment.read_bytes()),
        },
        "containers": legacy_adopt._application_containers(applications),
    }))
    manager = {
        "Image": old, "State": {"Running": True}, "Config": {"Cmd": None},
    }

    def scope(_project):
        return {**applications, "installation_manager": [manager]}

    def run(_config, path):
        fallback = path.name == "legacy-fallback.compose.yaml"
        manager["Image"] = old if fallback else new
        manager["Config"]["Cmd"] = None if fallback else ["candidate-web", config["data"]]

    monkeypatch.setattr(legacy_adopt, "_containers", scope)
    monkeypatch.setattr(legacy_adopt, "check_image", lambda reference: reference)
    monkeypatch.setattr(legacy_adopt, "_run_manager", run)
    monkeypatch.setattr(legacy_adopt, "_verify_roles", lambda *_args, **_kwargs: "original-postgres")
    monkeypatch.setattr(legacy_adopt.ComposeMaintenanceHost, "sql", lambda *_: "123:42")
    monkeypatch.setattr(legacy_adopt, "init_container", lambda *_: str(legacy_adopt.FORMAT_VERSION))

    def failed(*_):
        raise RuntimeError("Missing authenticated journal")

    assert not legacy_adopt.execute(config, store, operation.id, failed)
    assert manager["Image"] == old
    assert working.read_bytes() == b"legacy-runtime"
    assert not (tmp_path / ".bootstrap" / "current-release.json").exists()
    failure = store.first_failure(operation.id)
    assert failure.checkpoint.reason.value == "manager_unavailable"

    def probe(_config, current, operation_id, owner):
        assert manager["Image"] == new
        assert operation_id == operation.id
        assert current.get(operation_id).last_owner.claim_id == owner

    assert legacy_adopt.execute(config, store, operation.id, probe)
    assert working.read_bytes() == b"legacy-runtime-with-verified-manager"
    assert environment.read_bytes() == b"existing-values"
    assert store.get(operation.id).stage is OperationStage.SUCCEEDED
    assert store.get(operation.id).observation.observed_revision == "0070"
    assert store.first_failure(operation.id) == failure
