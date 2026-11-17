import io
import os
import tarfile
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from services.installation_manager.application import portable_restore
from services.installation_manager.domain.release_manifest import canonical_json, digest_of
from services.installation_manager.infrastructure import maintenance_archive


def _archive(path, members):
    with tarfile.open(path, "w:gz") as tar:
        for name, kind, value in members:
            member = tarfile.TarInfo(name)
            member.type = kind
            if member.isfile():
                member.size = len(value)
                tar.addfile(member, io.BytesIO(value))
            else:
                member.linkname = value
                tar.addfile(member)


@pytest.mark.parametrize(
    "members",
    [
        [("../escape", tarfile.REGTYPE, b"payload")],
        [
            ("parent", tarfile.SYMTYPE, "target"),
            ("target", tarfile.DIRTYPE, ""),
            ("parent/escape", tarfile.REGTYPE, b"payload"),
        ],
        [
            ("first", tarfile.SYMTYPE, "second"),
            ("second", tarfile.SYMTYPE, "first"),
        ],
        [
            ("a", tarfile.LNKTYPE, "../foreign"),
        ],
    ],
)
def test_extraction_rejects_unsafe_archive_before_writing(tmp_path, members):
    output = tmp_path / "output"
    output.mkdir()
    archive = tmp_path / "data.tar.gz"
    _archive(archive, members)

    with pytest.raises(ValueError):
        portable_restore.extract_data(archive, output)

    assert not list(output.iterdir())
    assert not (tmp_path / "escape").exists()


def test_extraction_preserves_regular_data_and_safe_hardlinks(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    archive = tmp_path / "data.tar.gz"
    _archive(archive, [
        ("extensions", tarfile.DIRTYPE, ""),
        ("extensions/input.txt", tarfile.REGTYPE, b"restored data"),
        ("extensions/link.txt", tarfile.LNKTYPE, "extensions/input.txt"),
    ])

    portable_restore.extract_data(archive, output)

    assert (output / "extensions" / "link.txt").read_bytes() == b"restored data"
    if os.name == "posix":
        assert (output / "extensions" / "input.txt").samefile(output / "extensions" / "link.txt")


def test_confirmed_manifest_is_bound_to_copy_time_and_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(portable_restore, "safe_path", lambda value: value)
    tmp_path.chmod(0o700)
    backup_id = uuid4()
    now = datetime.now(UTC).isoformat()
    files = {
        "database.dump": b"fixture-synthetic-db",
        "globals.sql": b"-- PostgreSQL database cluster dump\n"
                       b"-- PostgreSQL database cluster dump complete\n",
    }
    for name, value in files.items():
        (tmp_path / name).write_bytes(value)
        (tmp_path / name).chmod(0o600)
    archive = tmp_path / "data.tar.gz"
    for name in (".bootstrap", ".installation-state"):
        (tmp_path / name).mkdir()
    _archive(archive, [
        (name, tarfile.REGTYPE, b"protected-data")
        for name in sorted(maintenance_archive.REQUIRED_FILES)
    ])
    archive.chmod(0o600)
    manifest = {
        "format_version": 1, "operation_id": str(backup_id), "backup_id": str(backup_id),
        "instance_id": str(uuid4()), "compose_project": "a-project",
        "created_at": now, "source_revision": "0070", "source_digest": "sha256:" + "a" * 64,
        "artifacts": {
            name: maintenance_archive._fingerprint(tmp_path / name)
            for name in maintenance_archive.FILES
        },
    }
    content = canonical_json(manifest)
    (tmp_path / "manifest.json").write_bytes(content)
    (tmp_path / "manifest.json").chmod(0o600)

    metadata, public = portable_restore.inspect_copy(tmp_path)
    assert public["manifest_digest"] == digest_of(content)
    assert public["created_at"] == now
    assert "artifacts" not in public
    maintenance_archive.verify_copy_files(tmp_path, metadata)
    (tmp_path / "database.dump").write_bytes(b"fixture-synthetic-dB")
    with pytest.raises(ValueError, match="committed digests"):
        maintenance_archive.verify_copy_files(tmp_path, metadata)
    assert (tmp_path / "manifest.json").read_bytes() == content
