import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from services.installation_manager import candidate_executor, host_bootstrap
from services.installation_manager.domain.operation_state import (
    OperationKind,
    OperationRequest,
    OperationStage,
    ReleasePin,
)


def test_stock_executor_pin_changes_only_to_the_committed_manager(tmp_path, monkeypatch):
    control = tmp_path / host_bootstrap.CONTROL
    journal_dir = tmp_path / host_bootstrap.STATE
    control.mkdir()
    journal_dir.mkdir()
    old_image = "registry.example/manager@sha256:" + "1" * 64
    new_image = "registry.example/manager@sha256:" + "2" * 64
    config = {
        "data": str(tmp_path), "instance": str(uuid4()), "project": "dvt",
        "executor": old_image, "manager": old_image, "backup": "/saved-backup",
        "release_catalog": {"origin": "https://catalog.example"},
    }
    applied_id, next_id = str(uuid4()), str(uuid4())
    pin = {"release_id": "dvt-1.25.0", "manifest_digest": "sha256:" + "a" * 64}
    (control / "current-manager").write_text(new_image)
    (control / "current-release.json").write_text(json.dumps({
        "instance": config["instance"], "images": {"installation_manager": new_image},
        "operation": applied_id, **pin,
    }))
    db_path = journal_dir / "journal.sqlite3"
    with closing(sqlite3.connect(db_path)) as db:
        db.execute("CREATE TABLE operations (id TEXT, instance_id TEXT, stage TEXT, request TEXT)")
        db.execute("INSERT INTO operations VALUES (?, ?, 'resuming', ?)", (
            applied_id, config["instance"], json.dumps({"release": pin}),
        ))
        db.commit()

    def docker(*args):
        if args[1] == "ls":
            return SimpleNamespace(stdout="manager-container")
        return SimpleNamespace(stdout=json.dumps([{
            "Id": "manager-container", "Image": "pinned-image-id",
            "Config": {"Cmd": ["candidate-web", str(tmp_path)]},
        }]))

    monkeypatch.setattr(host_bootstrap, "safe_path", Path)
    monkeypatch.setattr(host_bootstrap, "active_operation", lambda _: (
        next_id, "admitted", json.dumps({"kind": "update"}),
    ))
    monkeypatch.setattr(host_bootstrap, "docker", docker)
    monkeypatch.setattr(host_bootstrap, "check_image", lambda _: "pinned-image-id")
    monkeypatch.setattr(host_bootstrap, "_executor_version", lambda _, image: (
        (1, 25, 0, 1, 0) if image == new_image else None
    ))
    monkeypatch.setattr(host_bootstrap, "atomic_write", Path.write_bytes)

    assert host_bootstrap._adopt_executor(config, next_id) == config
    assert not (control / "host.json").exists()
    with closing(sqlite3.connect(db_path)) as db:
        db.execute("UPDATE operations SET stage='succeeded' WHERE id=?", (applied_id,))
        db.commit()
    assert host_bootstrap._adopt_executor(config, next_id)["executor"] == new_image
    stored = json.loads((control / "host.json").read_bytes())
    assert stored == {**config, "executor": new_image}


def test_update_route_hands_later_step_to_preparer_version_required_by_manifest(tmp_path, monkeypatch):
    def operation(version):
        pin = ReleasePin(f"dvt-{version}", "sha256:" + "1" * 64)
        return SimpleNamespace(
            id=uuid4(), stage=OperationStage.ADMITTED,
            request=OperationRequest(OperationKind.UPDATE, pin),
        )

    first, second = operation("1.24.3"), operation("1.24.4")
    pending = [first, second]
    operations = {item.id: item for item in pending}
    store = SimpleNamespace(
        get=operations.get, artifact_path=lambda *_: tmp_path,
        route_root=lambda _: first.id, current_step=lambda _: pending[0] if pending else second,
    )
    config = {"data": str(tmp_path), "release_catalog": {"trust": {}}}
    versions = {first.request.release: "1.24.2", second.request.release: "1.24.3"}
    trust = SimpleNamespace(verify=lambda _, pin: SimpleNamespace(
        compatibility=SimpleNamespace(minimum_preparer_version=versions[pin]),
    ))
    dispatched = []
    applied = []

    def apply(_, __, item):
        assert pending.pop(0) is item
        applied.append(item.id)
        item.stage = OperationStage.SUCCEEDED

    monkeypatch.setattr(candidate_executor, "_execute_application", apply)
    monkeypatch.setattr(candidate_executor, "_preparer_version", lambda: "1.24.2")
    monkeypatch.setattr(candidate_executor, "read_selected_manifest", lambda *_: b"selected")
    monkeypatch.setattr(candidate_executor, "local_trust", lambda *_: trust)
    monkeypatch.setattr(candidate_executor, "_promotable_executor", lambda *_: (
        "new-executor", "committed-manager", (1, 24, 3, 1, 0),
    ))
    monkeypatch.setattr(candidate_executor, "docker", lambda *args: dispatched.append(args))
    candidate_executor.execute(config, store, first.id)
    assert applied == [first.id]
    assert dispatched == [(
        "container", "exec", "--detach", "committed-manager",
        "python3", "-m", "services.installation_manager", "candidate-executor-handoff",
        config["data"], str(second.id),
    )]

    monkeypatch.setattr(candidate_executor, "_preparer_version", lambda: "1.24.3")
    candidate_executor.execute(config, store, second.id)
    assert applied == [first.id, second.id]
    assert len(dispatched) == 1


def test_handoff_waits_for_old_runtime_even_when_it_owns_same_step(tmp_path, monkeypatch):
    operation_id, instance = str(uuid4()), str(uuid4())
    control = tmp_path / host_bootstrap.CONTROL
    control.mkdir()
    (control / "current-manager").write_text("new-image")
    old = SimpleNamespace(returncode=0, stdout=json.dumps([{
        "Config": {
            "Image": "old-image",
            "Labels": {"dvt.executor.operation": operation_id, "dvt.executor.instance": instance},
        },
        "State": {"Running": True},
    }]))
    docker = iter((old, SimpleNamespace(returncode=1)))
    monkeypatch.setattr(host_bootstrap, "docker", lambda *_args, **_kwargs: next(docker))
    monkeypatch.setattr(host_bootstrap, "active_id", lambda _: operation_id)
    monkeypatch.setattr(host_bootstrap.time, "sleep", lambda _: None)
    launched = []
    monkeypatch.setattr(host_bootstrap, "launch", lambda *args: launched.append(args))
    config = {"data": str(tmp_path), "instance": instance}
    host_bootstrap.launch_after_executor(config, operation_id)
    assert launched == [(config, operation_id)]
