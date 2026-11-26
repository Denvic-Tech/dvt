import json
import sqlite3
import subprocess
from contextlib import closing
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from services.installation_manager import (
    host_bootstrap,
    legacy_entry,
    legacy_entry_recovery as recovery,
    legacy_entry_supervisor as supervisor,
)
from services.installation_manager.domain.operation_state import OperationKind, OperationStage

INSTANCE = UUID("c1c6d593-d81f-42fb-88b6-e57a7217b2ac")
DIGEST = "sha256:" + "1" * 64
JOB = {"job_id": "legacy-abc", "project": "dvt", "kind": "update",
       "target_version": "1.24.0", "manifest_digest": DIGEST}


def test_waits_for_exact_old_upgrade_job_to_finish_before_handoff(monkeypatch):
    reply = {"id": "legacy-abc", "kind": "update", "version": "latest",
             "started_at": "2026-11-01T12:01:00Z"}
    snapshots = iter([{**reply, "state": "running"}, {**reply, "state": "succeeded"}])
    argv = []

    def docker(*args, **kwargs):
        argv.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps(next(snapshots)))

    monkeypatch.setattr(legacy_entry, "docker", docker)
    monkeypatch.setattr(legacy_entry.time, "sleep", lambda _: None)
    job = legacy_entry._job("a" * 64, "latest", datetime(2026, 11, 1, 19, 1, 1, tzinfo=UTC))
    assert job["id"] == "legacy-abc"
    assert len(argv) == 2
    assert all(call[:3] == ("exec", "a" * 64, "python3") for call in argv)


def test_supervisor_restores_unadmitted_predecessor_once(tmp_path, monkeypatch):
    restored = []

    def failed(*_):
        raise subprocess.CalledProcessError(1, "legacy-import")

    monkeypatch.setattr(supervisor, "safe_path", lambda path: path)
    monkeypatch.setattr(supervisor, "_read", lambda *_: str(INSTANCE).encode())
    monkeypatch.setattr(supervisor, "_update_command", failed)
    monkeypatch.setattr(supervisor.time, "sleep", lambda _: None)
    monkeypatch.setattr(recovery, "restore_before_admission", lambda *args: restored.append(args))
    (tmp_path / "installation").mkdir()
    package = tmp_path / "assets"

    assert supervisor.run(tmp_path, JOB, "bridge", package) == "restored"
    assert supervisor.run(tmp_path, JOB, "bridge", package) == "restored"
    assert restored == [(tmp_path, JOB, "bridge")]


def test_supervisor_after_daemon_restart_resumes_current_step_without_readmitting(
    tmp_path, monkeypatch,
):
    launched = []
    (tmp_path / "installation").mkdir()
    state = tmp_path / supervisor.STATE
    state.mkdir()
    (state / "journal.sqlite3").touch()
    step_id = UUID("6f6925d3-31c5-4dce-8a2a-f26d729f3631")
    steps = iter((
        SimpleNamespace(id=step_id, stage=OperationStage.MIGRATING),
        SimpleNamespace(
            id=step_id, stage=OperationStage.SUCCEEDED,
            request=SimpleNamespace(release=SimpleNamespace(manifest_digest=DIGEST)),
        ),
    ))
    store = SimpleNamespace(current_step=lambda _: next(steps))
    monkeypatch.setattr(supervisor.OperationStore, "for_host", lambda _: store)
    monkeypatch.setattr(supervisor, "safe_path", lambda path: path)
    monkeypatch.setattr(supervisor, "_read", lambda *_: str(INSTANCE).encode())
    monkeypatch.setattr(supervisor, "load_host", lambda _: {"config": True})
    monkeypatch.setattr(supervisor, "_executor_running", lambda _: False)
    monkeypatch.setattr(supervisor, "launch", lambda *args: launched.append(args))
    monkeypatch.setattr(supervisor.time, "sleep", lambda _: None)
    monkeypatch.setattr(recovery, "restore_before_admission", lambda *_: pytest.fail("Unsafe rollback"))

    assert supervisor.run(tmp_path, JOB, "bridge", tmp_path) == "succeeded"
    assert launched == [({"config": True}, str(step_id))]


def test_rollback_refuses_any_managed_control_before_touching_legacy_files(tmp_path, monkeypatch):
    (tmp_path / recovery.CONTROL).mkdir()
    monkeypatch.setattr(recovery, "capture_backups", lambda *_: pytest.fail("Rollback attempted"))
    with pytest.raises(ValueError, match="Managed recovery"):
        recovery.restore_before_admission(tmp_path, JOB, "bridge")


def test_host_network_handoff_disables_restart_using_docker_name(tmp_path, monkeypatch):
    marker = {**JOB, "format_version": 1, "requested_version": "1.24.0"}
    image = "registry.example/dvt/installation_manager@" + DIGEST
    name, token = legacy_entry._handoff_identity(marker)
    cid = "a" * 64
    updates = []

    def inspect(supplied_name):
        assert supplied_name == name
        return [{
            "Id": cid, "Name": f"/{name}", "HostConfig": {"NetworkMode": "host"},
            "Config": {
                "Image": image, "Labels": {f"{legacy_entry.LABEL}.handoff": token},
                "Cmd": legacy_entry._handoff_arguments(tmp_path, JOB["job_id"], image),
            },
        }]

    monkeypatch.setenv("HOSTNAME", "host-network-reuses-another-hostname")
    monkeypatch.setattr(host_bootstrap, "safe_path", lambda path: path)
    monkeypatch.setattr(legacy_entry, "read_artifact", lambda *_: json.dumps(marker).encode())
    monkeypatch.setattr(legacy_entry, "_inspect", inspect)
    monkeypatch.setattr(legacy_entry, "docker", lambda *args, **_: updates.append(args))
    monkeypatch.setattr(supervisor, "run", lambda *_: "restored")

    legacy_entry.handoff(tmp_path, JOB["job_id"], image)

    assert updates == [("update", "--restart=no", cid)]


@pytest.mark.parametrize("admitted", [False, True])
def test_quarantine_only_own_partial_bootstrap_with_no_admitted_operation(
    tmp_path, monkeypatch, admitted,
):
    marker = {**JOB, "managed_paths_absent": True}
    image = "registry.example/dvt/installation_manager@" + DIGEST
    config = {
        "version": 1, "instance": str(INSTANCE), "data": str(tmp_path), "project": JOB["project"],
        "manager": image, "executor": image, "candidate": image,
    }
    (tmp_path / "installation").mkdir()
    (tmp_path / recovery.CONTROL).mkdir()
    (tmp_path / recovery.CONTROL / "host.json").write_text(json.dumps(config))
    (tmp_path / recovery.STATE).mkdir()
    journal = tmp_path / recovery.STATE / "journal.sqlite3"
    with closing(sqlite3.connect(journal)) as db:
        db.execute("PRAGMA application_id = 0x44565449")
        db.execute(f"PRAGMA user_version = {recovery.FORMAT_VERSION}")
        db.execute("CREATE TABLE operations (id TEXT)")
        db.execute("CREATE TABLE identity (instance_id TEXT)")
        if admitted:
            db.execute("INSERT INTO operations VALUES ('already-admitted')")
        db.commit()
    monkeypatch.setattr(recovery, "safe_path", lambda path: path)
    monkeypatch.setattr(recovery, "_read", lambda path, _: path.read_bytes())
    monkeypatch.setattr(recovery, "docker", lambda *_: SimpleNamespace(stdout=""))
    monkeypatch.setattr(recovery, "sync_directory", lambda _: None)

    if admitted:
        with pytest.raises(ValueError, match="An admitted operation"):
            recovery._quarantine_unadmitted(tmp_path, marker, image, INSTANCE)
        assert journal.is_file()
    else:
        recovery._quarantine_unadmitted(tmp_path, marker, image, INSTANCE)
        assert not journal.exists()
        assert not (tmp_path / recovery.CONTROL).exists()
        [saved] = (tmp_path / "installation").glob(".legacy-unadmitted-*")
        assert (saved / recovery.STATE / journal.name).is_file()
        assert json.loads((saved / recovery.CONTROL / "host.json").read_text()) == config


@pytest.mark.parametrize(
    ("stage", "root_operation", "phase", "expected"),
    [
        (OperationStage.PREPARING, True, "starting", "restored"),
        (OperationStage.PREPARED, True, "starting", "restored"),
        (OperationStage.MAINTENANCE, True, "restoring_admitted", "restored"),
        (OperationStage.BACKUP, True, "starting", "restored"),
        (OperationStage.CANCELLED, True, "restoring_admitted", "restored"),
        (OperationStage.PREPARING, False, "starting", "operator_required"),
        (OperationStage.MIGRATING, True, "starting", "operator_required"),
    ],
)
def test_exhausted_supervisor_only_restores_admitted_legacy_root_before_migration(
    tmp_path, monkeypatch, stage, root_operation, phase, expected,
):
    root_id = supervisor._operation_id(JOB["job_id"], INSTANCE)
    step_id = root_id if root_operation else UUID("6f6925d3-31c5-4dce-8a2a-f26d729f3631")
    (tmp_path / "installation").mkdir()
    (tmp_path / supervisor.STATE).mkdir()
    (tmp_path / supervisor.STATE / "journal.sqlite3").touch()
    status = {
        "job_id": JOB["job_id"], "manifest_digest": DIGEST, "step": str(step_id),
        "phase": phase, "starts": supervisor.MAX_STARTS,
    }
    (tmp_path / supervisor.STATUS).write_text(json.dumps(status), encoding="utf-8")
    operation = SimpleNamespace(
        id=step_id, stage=stage, request=SimpleNamespace(kind=OperationKind.UPDATE),
    )
    store = SimpleNamespace(current_step=lambda _root_id: operation)
    calls = []
    monkeypatch.setattr(supervisor.OperationStore, "for_host", lambda _: store)
    monkeypatch.setattr(supervisor, "safe_path", lambda path: path)
    monkeypatch.setattr(supervisor, "_read", lambda *_: str(INSTANCE).encode())
    monkeypatch.setattr(supervisor, "load_host", lambda _: {"project": "dvt"})
    monkeypatch.setattr(supervisor, "_executor_running", lambda _: False)
    monkeypatch.setattr(supervisor, "launch", lambda *_: pytest.fail("Retries were exhausted"))
    monkeypatch.setattr(
        supervisor, "return_to_legacy", lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert supervisor.run(tmp_path, JOB, "bridge", tmp_path) == expected
    assert json.loads((tmp_path / supervisor.STATUS).read_text(encoding="utf-8"))["phase"] == expected
    if expected == "restored" and not stage.terminal:
        assert calls == [(({"project": "dvt"}, store, root_id), {"legacy_job": JOB})]
    else:
        assert calls == []
