from __future__ import annotations

import json
import os
import tarfile
from uuid import uuid4

import pytest

from services.installation_manager.infrastructure.maintenance_archive import (
    REQUIRED_FILES,
    backup_exclusions,
    create_copy,
)


class _DatabaseFixture:
    payload = b"PGDMP fixture - a remote PostgreSQL smoke verifies the actual format"
    globals = (
        b"-- PostgreSQL database cluster dump\n"
        b"CREATE ROLE fixture;\n"
        b"-- PostgreSQL database cluster dump complete\n"
    )

    def __init__(self, data):
        self.data = data
        self.reads = 0

    def postgres_tool(self, _container, name, stream, *, verify=False):
        if verify:
            assert name == "database.dump"
            assert stream.read() == self.payload
            self.reads += 1
        else:
            stream.write(self.payload if name == "database.dump" else self.globals)


def test_backup_contains_config_extensions_and_verified_dump_excluding_transient_data(tmp_path):
    operation_id = uuid4()
    data = tmp_path / "dvt"
    backup = tmp_path / "another-filesystem"
    temporary = data / "temp"
    pgdata = data / "data" / "pgdata"
    backup.mkdir()
    host = _DatabaseFixture(data)
    files = {
        **{name: f"fixture {name}".encode() for name in REQUIRED_FILES},
        "extensions/fixture/node.py": b"node fixture",
        "installation/instance_id": b"fixture-instance",
        ".bootstrap/pairing.json": b"transient",
        "data/pgdata/PG_VERSION": b"15",
        "temp/download.part": b"transient",
        "data/valkeydata/dump.rdb": b"valkey-data",
    }
    for name, contents in files.items():
        path = data / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    excluded = backup_exclusions(data, backup, temporary, pgdata)
    metadata = {
        "backup_id": str(operation_id),
        "layout": {"excluded_paths": sorted(excluded)},
    }
    create_copy(backup, operation_id, metadata, host, "postgres", confirm_source_sealed=lambda: None)
    create_copy(backup, operation_id, metadata, host, "postgres", confirm_source_sealed=lambda: None)
    assert host.reads == 2

    published = backup / str(operation_id)
    assert list(backup.iterdir()) == [published]
    assert json.loads((published / "manifest.json").read_text())["backup_id"] == str(operation_id)
    with tarfile.open(published / "data.tar.gz", "r:gz") as archive:
        assert {item.name for item in archive.getmembers() if item.isfile()} == {
            name for name in files if not any(
                name == path or name.startswith(f"{path}/") for path in excluded
            )
        }
        assert archive.extractfile("extensions/fixture/node.py").read() == files[
            "extensions/fixture/node.py"
        ]
    if os.name == "posix":
        assert published.stat().st_mode & 0o777 == 0o700
        assert all(path.stat().st_mode & 0o777 == 0o600 for path in published.iterdir())

    with (published / "database.dump").open("ab") as stream:
        stream.write(b"x")
    with pytest.raises(ValueError, match="digests"):
        create_copy(
            backup, operation_id, metadata, host, "postgres", confirm_source_sealed=lambda: None
        )


def test_failed_dump_is_not_published_and_retry_uses_same_identity(tmp_path):
    operation_id = uuid4()
    backup = tmp_path / "backup"
    backup.mkdir()
    data = tmp_path / "dvt"
    for name in REQUIRED_FILES:
        path = data / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    class Interrupted(_DatabaseFixture):
        def postgres_tool(self, _container, name, stream, *, verify=False):
            if name == "globals.sql":
                raise OSError("copy interrupted")
            super().postgres_tool(_container, name, stream, verify=verify)

    metadata = {"backup_id": str(operation_id), "layout": {"excluded_paths": []}}
    with pytest.raises(OSError, match="interrupted"):
        create_copy(
            backup, operation_id, metadata, Interrupted(data), "postgres",
            confirm_source_sealed=lambda: None,
        )
    assert list(backup.iterdir()) == []
    create_copy(
        backup, operation_id, metadata, _DatabaseFixture(data), "postgres",
        confirm_source_sealed=lambda: None,
    )
    assert (backup / str(operation_id) / "manifest.json").exists()
