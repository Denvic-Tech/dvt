from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "scripts" / ".pre_commit" / "check_migration_revisions.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_migration_revisions", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_migration(
    path: Path,
    revision: str,
    down_revision: str | tuple[str, ...] | None = None,
    *,
    depends_on: str | tuple[str, ...] | None = None,
) -> None:
    path.write_text(
        "\n".join(
            [
                '"""Test migration."""',
                "",
                f"revision: str = {revision!r}",
                f"down_revision = {down_revision!r}",
                f"depends_on = {depends_on!r}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_find_duplicate_revisions_returns_empty_mapping_when_revisions_are_unique(
    tmp_path: Path,
) -> None:
    module = load_module()
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    write_migration(versions_dir / "0001_first.py", "0001")
    write_migration(versions_dir / "0002_second.py", "0002", "0001")

    assert module.find_duplicate_revisions(versions_dir) == {}


def test_find_duplicate_revisions_groups_files_with_same_revision(tmp_path: Path) -> None:
    module = load_module()
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    write_migration(versions_dir / "0001_first.py", "0001")
    write_migration(versions_dir / "0001_duplicate.py", "0001")
    write_migration(versions_dir / "0002_second.py", "0002", "0001")

    duplicates = module.find_duplicate_revisions(versions_dir)

    assert list(duplicates) == ["0001"]
    assert [path.name for path in duplicates["0001"]] == [
        "0001_duplicate.py",
        "0001_first.py",
    ]


def test_validate_migration_graph_returns_single_base_and_head(tmp_path: Path) -> None:
    module = load_module()
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    write_migration(versions_dir / "0001_first.py", "0001")
    write_migration(versions_dir / "0002_second.py", "0002", "0001")
    write_migration(versions_dir / "0003_third.py", "0003", "0002")

    graph = module.validate_migration_graph(versions_dir)

    assert graph.base == "0001"
    assert graph.head == "0003"


def test_validate_migration_graph_accepts_merge_revision(tmp_path: Path) -> None:
    module = load_module()
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    write_migration(versions_dir / "0001_base.py", "0001")
    write_migration(versions_dir / "0002_left.py", "0002", "0001")
    write_migration(versions_dir / "0003_right.py", "0003", "0001")
    write_migration(
        versions_dir / "0004_merge.py",
        "0004",
        ("0002", "0003"),
    )

    assert module.validate_migration_graph(versions_dir).head == "0004"


def test_validate_migration_graph_rejects_non_four_digit_revision(tmp_path: Path) -> None:
    module = load_module()
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    write_migration(versions_dir / "invalid.py", "feature_head")

    with pytest.raises(module.MigrationValidationError, match="exactly four digits"):
        module.validate_migration_graph(versions_dir)


def test_validate_migration_graph_rejects_duplicate_ids_after_rebase(tmp_path: Path) -> None:
    module = load_module()
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    write_migration(versions_dir / "first.py", "0001")
    write_migration(versions_dir / "duplicate.py", "0001")

    with pytest.raises(module.MigrationValidationError, match="after merge/rebase"):
        module.validate_migration_graph(versions_dir)


def test_validate_migration_graph_rejects_multiple_heads(tmp_path: Path) -> None:
    module = load_module()
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    write_migration(versions_dir / "0001_base.py", "0001")
    write_migration(versions_dir / "0002_left.py", "0002", "0001")
    write_migration(versions_dir / "0003_right.py", "0003", "0001")

    with pytest.raises(module.MigrationValidationError, match="exactly one Alembic head"):
        module.validate_migration_graph(versions_dir)


def test_validate_migration_graph_rejects_missing_parent(tmp_path: Path) -> None:
    module = load_module()
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    write_migration(versions_dir / "0002.py", "0002", "deleted_revision")

    with pytest.raises(module.MigrationValidationError, match="missing revision"):
        module.validate_migration_graph(versions_dir)


def test_validate_migration_graph_rejects_cycle(tmp_path: Path) -> None:
    module = load_module()
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    write_migration(versions_dir / "0001.py", "0001", "0002")
    write_migration(versions_dir / "0002.py", "0002", "0001")

    with pytest.raises(module.MigrationValidationError, match="Cycle found"):
        module.validate_migration_graph(versions_dir)


def test_sync_release_preserves_future_fields_and_comments(tmp_path: Path) -> None:
    module = load_module()
    release_path = tmp_path / "RELEASE"
    release_path.write_text(
        "# Release metadata\n"
        "RELEASE_FORMAT_VERSION=1\n"
        "VERSION=2.3.4\n"
        "ALEMBIC_REVISION=0001\n",
        encoding="utf-8",
    )

    assert module.sync_release(release_path, "0002") is True
    assert release_path.read_text(encoding="utf-8") == (
        "# Release metadata\n"
        "RELEASE_FORMAT_VERSION=1\n"
        "VERSION=2.3.4\n"
        "ALEMBIC_REVISION=0002\n"
    )
    assert module.sync_release(release_path, "0002") is False


def test_deleted_leaf_revision_updates_release_to_previous_head(tmp_path: Path) -> None:
    module = load_module()
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    write_migration(versions_dir / "0001.py", "0001")
    deleted_path = versions_dir / "0002.py"
    write_migration(deleted_path, "0002", "0001")
    release_path = tmp_path / "RELEASE"
    release_path.write_text(
        "RELEASE_FORMAT_VERSION=1\nALEMBIC_REVISION=0002\n",
        encoding="utf-8",
    )
    deleted_path.unlink()

    graph = module.validate_migration_graph(versions_dir)

    assert graph.head == "0001"
    assert module.sync_release(release_path, graph.head) is True
    assert "ALEMBIC_REVISION=0001" in release_path.read_text(encoding="utf-8")


def test_post_write_mode_updates_release_and_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    versions_dir = tmp_path / "migrations" / "versions"
    versions_dir.mkdir(parents=True)
    write_migration(versions_dir / "0001.py", "0001")
    generated_path = versions_dir / "0002.py"
    write_migration(generated_path, "0002", "0001")
    release_path = tmp_path / "RELEASE"
    release_path.write_text(
        "RELEASE_FORMAT_VERSION=1\nALEMBIC_REVISION=0001\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "VERSIONS_DIR", versions_dir)
    monkeypatch.setattr(module, "RELEASE_PATH", release_path)

    assert module.main(["--post-write", str(generated_path)]) == 0
    assert "ALEMBIC_REVISION=0002" in release_path.read_text(encoding="utf-8")


def test_post_write_mode_rejects_generated_file_outside_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    versions_dir = tmp_path / "migrations" / "versions"
    versions_dir.mkdir(parents=True)
    write_migration(versions_dir / "0001.py", "0001")
    generated_path = tmp_path / "0002.py"
    write_migration(generated_path, "0002", "0001")
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "VERSIONS_DIR", versions_dir)
    monkeypatch.setattr(module, "RELEASE_PATH", tmp_path / "RELEASE")

    assert module.main(["--post-write", str(generated_path)]) == 1


@pytest.mark.parametrize(
    "content, message",
    [
        ("RELEASE_FORMAT_VERSION=2\n", "unsupported"),
        ("ALEMBIC_REVISION=0001\nALEMBIC_REVISION=0002\n", "duplicate key"),
        ("export ALEMBIC_REVISION=0001\n", "KEY=VALUE"),
        ("ALEMBIC_REVISION=${HEAD}\n", "substitutions"),
        ("ALEMBIC_REVISION=feature_head\n", "invalid"),
    ],
)
def test_parse_release_text_rejects_ambiguous_content(content: str, message: str) -> None:
    module = load_module()

    with pytest.raises(module.ReleaseValidationError, match=message):
        module.parse_release_text(content)
