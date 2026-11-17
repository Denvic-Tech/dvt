from types import SimpleNamespace
from uuid import uuid4

import pytest

from services.installation_manager.application import application_apply as apply
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


def test_apply_waits_for_full_readiness_and_retries_resume_without_migration(tmp_path, monkeypatch):
    store = OperationStore.for_host(tmp_path)
    identity = InstanceIdentity(uuid4(), "/test", "test", "127.0.0.1", 18888, "http://test:18080")
    store.establish_identity(identity)
    manifest = "sha256:" + "1" * 64
    gateway = "sha256:" + "2" * 64
    request = OperationRequest(OperationKind.INSTALL, ReleasePin("fixture", manifest))
    operation = store.admit(request, idempotency_key="fixture")
    with store.claim(operation.id) as owner:
        owner.checkpoint(Checkpoint(OperationStage.PREPARING))
        owner.checkpoint(
            Checkpoint(OperationStage.PREPARED, observation=Observation(target_revision="0070"))
        )

    control = tmp_path / apply.CONTROL
    control.mkdir()
    path = control / "current-release.json"
    config = {"data": str(tmp_path)}
    plan = {"services": {"gateway": "fixture/gateway@" + gateway}, "profiles": []}
    environment = {"DVT_TASK_WORKERS_COUNT": "1"}
    calls = []
    state = {
        "postgres": False,
        "migrated": False,
        "ready": False,
        "resumed": False,
        "historical": False,
        "receipt": False,
    }
    release = SimpleNamespace(
        version="1.2.3",
        release_id="fixture",
        database_schema=SimpleNamespace(required_extensions=[]),
    )

    class Host:
        def __init__(self, _config, directory, _model, _plan, _deadline):
            self.path = directory / "application.compose.yaml"

        @staticmethod
        def bind_images():
            pass

        @staticmethod
        def containers():
            return {"postgres": [object()]} if state["postgres"] else {}

        @staticmethod
        def database_identity(_pg):
            return "123:456"

        @staticmethod
        def up(service=None, **_kwargs):
            calls.append((service, store.get(operation.id).stage))
            if service == "postgres":
                state["postgres"] = True
            return True

        @staticmethod
        def wait_for_database():
            return "postgres"

        @staticmethod
        def phase(*_args):
            return "done" if state["receipt"] else None

        @staticmethod
        def migration_locked(_pg):
            return False

        @staticmethod
        def revision(*_args):
            return "0070" if state["migrated"] else None

        @staticmethod
        def migration_done(*_args):
            return state["migrated"]

        @staticmethod
        def wait_for_migration(*_args):
            state["migrated"] = True

        @staticmethod
        def app_ready(*_args):
            return state["ready"]

        @staticmethod
        def wait_for_application(*_args):
            return state["ready"]

        @staticmethod
        def retire_stopped_services():
            pass

        @staticmethod
        def restore_restart_policy():
            assert state["ready"]

        @staticmethod
        def resume(*_args):
            assert store.get(operation.id).stage is OperationStage.RESUMING
            assert path.is_file()  # Durable pointer precedes opening admission.
            return state["resumed"]

    def staged(*_args):
        return (
            release,
            plan,
            {"services": {k: {} for k in apply.MANAGED_ROLES | {"installation_manager"}}},
            environment,
            None,
            state["historical"],
        )

    monkeypatch.setattr(apply, "ComposeApplicationHost", Host)
    monkeypatch.setattr(apply.ApplicationApply, "_staged", staged)
    monkeypatch.setattr(apply.ApplicationApply, "_support", lambda *_: None)
    monkeypatch.setattr(apply.ApplicationApply, "_manager_images", lambda *_: ("old", "new"))
    monkeypatch.setattr(apply.ApplicationApply, "_apply_manager_health", lambda *_: None)
    executor = apply.ApplicationApply(store, config, lambda *_: None)
    executor.execute(operation.id)
    assert store.get(operation.id).stage is OperationStage.VERIFYING
    assert not path.exists()
    assert not (tmp_path / ".env").exists()
    assert calls == [
        ("postgres", OperationStage.MIGRATING),
        ("migrate", OperationStage.MIGRATING),
        (None, OperationStage.APPLYING),
    ]

    state["ready"] = True
    state["historical"] = True
    executor.execute(operation.id)
    assert store.get(operation.id).stage is OperationStage.VERIFYING
    assert not path.exists()

    state["receipt"] = True
    executor.execute(operation.id)
    assert store.get(operation.id).stage is OperationStage.RESUMING
    assert path.is_file()
    assert (tmp_path / ".env").is_file()
    assert (tmp_path / "docker-compose.yaml").is_file()
    assert len(calls) == 3

    state["resumed"] = True
    executor.execute(operation.id)
    result = store.get(operation.id)
    assert result.stage is OperationStage.SUCCEEDED
    assert result.observation.observed_digest == gateway
    assert len(calls) == 3


def test_missing_target_manager_restores_previous_digest_at_same_address(tmp_path, monkeypatch):
    control = tmp_path / apply.CONTROL
    control.mkdir()
    operation_id = uuid4()
    claim_id = uuid4()
    owner = SimpleNamespace(record=SimpleNamespace(claim_id=claim_id))
    operation = SimpleNamespace(id=operation_id)
    previous = "fixture/manager@sha256:" + "3" * 64
    target = "fixture/manager@sha256:" + "4" * 64
    config = {"data": str(tmp_path), "address": "127.0.0.1", "port": 18888}
    host = SimpleNamespace(containers=dict)
    effects = []

    def replace_manager(host_config, reference, _path):
        effects.append((host_config["address"], host_config["port"], reference))

    def probe(_config, _store, requested_operation, requested_claim):
        assert effects == [("127.0.0.1", 18888, previous)]
        assert (requested_operation, requested_claim) == (operation_id, claim_id)

    monkeypatch.setattr(apply, "apply_manager", replace_manager)
    with pytest.raises(apply.ApplyError, match="Restored the previous web manager"):
        apply.ApplicationApply(None, config, probe)._apply_manager_health(
            host, tmp_path, (previous, target), operation, owner
        )
    assert (control / "current-manager").read_text() == previous
