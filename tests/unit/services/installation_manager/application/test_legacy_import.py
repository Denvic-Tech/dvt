from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from services.installation_manager.application import legacy_import as importer
from services.installation_manager.domain.operation_state import (
    FailureReason,
    Observation,
    OperationKind,
    OperationRequest,
    OperationStage,
    ReleasePin,
)
from services.installation_manager.domain.release_manifest import StagingError, canonical_json


def test_legacy_source_backups_are_paired_in_update_order(tmp_path):
    env = tmp_path / ".env.bak.20261123110000"
    compose = tmp_path / "docker-compose.yaml.bak.20261123113005"
    for file in (env, compose):
        file.touch()
    assert importer._backups(tmp_path) == (env, compose)
    (tmp_path / ".env.bak.20261123120000").touch()
    with pytest.raises(ValueError, match="same attempt"):
        importer._backups(tmp_path)


def test_pgdata_keeps_postgres_owned_subdirectory(tmp_path):
    data = tmp_path / "dvt"
    pgdata = data / "data" / "pgdata"
    pgdata.mkdir(parents=True, mode=0o700)
    if hasattr(importer.os, "geteuid") and importer.os.geteuid() == 0:
        importer.os.chown(pgdata, 999, 999)
    assert importer._pgdata(data, str(pgdata)) == pgdata
    with pytest.raises(ValueError, match="outside"):
        importer._pgdata(data, tmp_path)
    with pytest.raises(ValueError, match="outside"):
        importer._pgdata(data, data)


@pytest.mark.parametrize(("version", "revision", "canonical"), [
    ("1.22.0", "0061", "1.22.0"),
    ("1.23.0", "0063", "1.23.0"),
    ("1.24.0-rc1", "0065", "1.24.0-rc1"),
    ("1.24.0rc2", "0068", "1.24.0-rc2"),
    ("1.24.0-rc3", "0069", "1.24.0-rc3"),
    ("1.24.0-rc4", "0070", "1.24.0-rc4"),
    ("1.24.0-rc5", "0063", "1.24.0-rc5"),
    ("1.24.0-rc12", "0070", "1.24.0-rc12"),
    ("latest", "0070", "latest"),
])
def test_legacy_source_version_checks_released_database_head(version, revision, canonical):
    assert importer.legacy_source_version(version, revision) == canonical


@pytest.mark.parametrize(("version", "revision"), [
    ("1.24.0", "0070"),
    ("1.24.0-rc1", "0068"),
    ("1.24.0-rc99", "0070"),
    ("latest", "0066"),
])
def test_legacy_source_version_rejects_undeclared_pairs(version, revision):
    with pytest.raises(ValueError, match="database revision are unsupported"):
        importer.legacy_source_version(version, revision)


def test_previously_completed_rc_migrator_is_replaced_by_target(monkeypatch):
    legacy = {"Id": "rc-migrate", "State": {"Status": "exited", "Running": False, "ExitCode": 0}}
    target = {"Id": "target-migrate", "State": dict(legacy["State"])}
    pg = {"Id": "pg", "State": {"Health": {"Status": "healthy"}}}
    roles = {"postgres": [pg], "migrate": [legacy]}
    host = SimpleNamespace(
        config={},
        revision=lambda _: "0070",
        database_identity=lambda _: "1:2",
        is_target=lambda _, row: row is not legacy,
        postgres=lambda _: "pg",
        sql=lambda _, sql: "0" if sql == importer.ONLY_LOCAL_CLIENT else "open",
    )
    importer.check_historical_migrator(roles, {"migrate": {}})
    with pytest.raises(ValueError, match="unexpected or active"):
        importer.check_historical_migrator(roles, {})

    def run_role(actual, role):
        assert (actual, role) == (host, "migrate")
        roles["migrate"] = [target]

    monkeypatch.setattr(importer, "_rows", lambda *_: roles)
    monkeypatch.setattr(importer, "_run_roles", run_role)
    importer._migrate(host, {"source_revision": "0070", "database": "1:2"}, "0070")
    assert roles["migrate"] == [target]


def test_old_job_uuid_is_preserved_and_opaque_job_ids_are_stable():
    operation = uuid4()
    instance = uuid4()
    assert importer._operation_id(str(operation), instance) == operation
    assert importer._operation_id("legacy-code", instance) == importer._operation_id(
        "legacy-code", instance
    )
    assert importer._operation_id("legacy-code", instance) != importer._operation_id(
        "legacy-code", uuid4()
    )


def test_legacy_rollback_cannot_restart_the_old_application_after_migration_is_authorized(
    tmp_path,
    monkeypatch,
):
    operation_id = uuid4()
    operation = SimpleNamespace(stage=OperationStage.MIGRATING)
    store = SimpleNamespace(get=lambda _: operation, claim=lambda _: nullcontext(None))
    monkeypatch.setattr(importer, "artifact_directory", lambda *_: tmp_path)
    monkeypatch.setattr(importer, "docker", lambda *_: pytest.fail("Docker was called"))
    with pytest.raises(ValueError, match="only available before migration"):
        importer.return_to_legacy({"data": str(tmp_path)}, store, operation_id)


def test_apply_starts_roles_without_restarting_verified_migration(tmp_path, monkeypatch):
    instance, operation_id = uuid4(), uuid4()
    config = {"instance": str(instance), "data": str(tmp_path), "project": "dvt"}
    operation = SimpleNamespace(
        request=OperationRequest(OperationKind.UPDATE, ReleasePin("baseline", "sha256:" + "0" * 64)),
        stage=OperationStage.APPLYING,
        instance_id=instance,
        id=operation_id,
    )
    (tmp_path / importer.PLAN).write_bytes(canonical_json({
        "legacy_job_id": str(operation_id), "source_version": "1.24.0-rc1",
        "source_revision": "0065", "target_version": "1.24.0",
    }))
    started = []
    stages = []

    def checkpoint(value):
        stages.append(value.stage)
        return value

    def database_wait():
        raise RuntimeError("The application is still preparing")

    owner = SimpleNamespace(checkpoint=checkpoint)
    store = SimpleNamespace(get=lambda _: operation, claim=lambda _: nullcontext(owner))
    release = SimpleNamespace(database_schema=SimpleNamespace(target_revision="0070"))
    host = SimpleNamespace(
        config=config, path=tmp_path / "application.compose.yaml",
        services={"migrate": {}, "gateway": {}, "proxy": {}}, wait_for_database=database_wait,
    )
    monkeypatch.setattr(importer, "artifact_directory", lambda *_: tmp_path)
    monkeypatch.setattr(importer, "_target", lambda *_: (host, release, b"", {}))
    monkeypatch.setattr(importer, "_rows", lambda *_: {})
    monkeypatch.setattr(importer, "docker", lambda *args: started.append(args))

    importer.execute(config, store, operation_id, None)

    assert len(started) == 1
    assert started[0][-2:] == ("gateway", "proxy")
    assert "--no-deps" in started[0]
    assert stages == [OperationStage.VERIFYING, OperationStage.VERIFYING]


def test_corrupt_backup_blocks_all_migration_on_resume(tmp_path, monkeypatch):
    instance, operation_id = uuid4(), uuid4()
    pin = ReleasePin("baseline", "sha256:" + "0" * 64)
    config = {"instance": str(instance), "data": str(tmp_path), "backup": str(tmp_path)}
    operation = SimpleNamespace(
        request=OperationRequest(OperationKind.UPDATE, pin),
        stage=OperationStage.MIGRATING,
        instance_id=instance,
        id=operation_id,
        observation=Observation(backup_id=operation_id),
    )
    saved = {
        "legacy_job_id": str(operation_id),
        "source_version": "1.23.0",
        "source_revision": "0063",
        "target_version": "1.24.0",
        "target_manifest_digest": pin.manifest_digest,
    }
    (tmp_path / importer.PLAN).write_bytes(canonical_json(saved))
    (tmp_path / "legacy-backup-layout.json").write_bytes(b"{}")
    checkpoints = []
    owner = SimpleNamespace(checkpoint=checkpoints.append)
    store = SimpleNamespace(get=lambda _: operation, claim=lambda _: nullcontext(owner))
    release = SimpleNamespace(database_schema=SimpleNamespace(target_revision="0069"))
    monkeypatch.setattr(importer, "artifact_directory", lambda *_: tmp_path)
    monkeypatch.setattr(importer, "safe_path", Path)
    monkeypatch.setattr(importer, "_target", lambda *_: (object(), release, b"", {}))
    monkeypatch.setattr(importer, "_rows", lambda *_: {"postgres": [{"Id": "db-container"}]})

    def corrupt_backup(*_):
        raise StagingError(FailureReason.BACKUP, "Corrupt dump", "Recover from a verified backup")

    monkeypatch.setattr(importer, "verify_copy", corrupt_backup)
    monkeypatch.setattr(importer, "_migrate", lambda *_: pytest.fail("migration was attempted"))
    importer.execute(config, store, operation_id, None)
    assert checkpoints[0].stage is OperationStage.MIGRATING
    assert checkpoints[0].reason is FailureReason.BACKUP
