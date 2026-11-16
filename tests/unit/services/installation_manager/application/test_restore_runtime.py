from types import SimpleNamespace
from uuid import uuid4

import pytest

from services.installation_manager.application import restore_runtime
from services.installation_manager.application.restore_runtime import (
    FunctionalProof,
    RestoreRuntime,
)
from services.installation_manager.domain.operation_state import (
    Checkpoint,
    InstanceIdentity,
    Observation,
    OperationKind,
    OperationRequest,
    OperationStage,
    ReleasePin,
)
from services.installation_manager.infrastructure.operation_store import OperationStore


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
