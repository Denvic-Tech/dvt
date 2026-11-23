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
