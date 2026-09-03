import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.extensions import deletion_queue


def _configure_queue(monkeypatch, tmp_path: Path) -> Path:
    extensions_root = tmp_path / "extensions"
    extensions_root.mkdir()
    monkeypatch.setattr(
        deletion_queue.config.EXTENSIONS, "EXTENSIONS_DATA_DIR", extensions_root
    )
    monkeypatch.setattr(
        deletion_queue.config.EXTENSIONS,
        "PENDING_DELETIONS_FILE",
        tmp_path / "pending.json",
    )
    return extensions_root


def test_pending_deletion_rejects_path_outside_extensions_root(
    monkeypatch, tmp_path: Path
) -> None:
    _configure_queue(monkeypatch, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ValueError):
        deletion_queue.add_pending_deletion("outside", outside)


def test_pending_deletion_deduplicates_and_processes_atomically(
    monkeypatch, tmp_path: Path
) -> None:
    extensions_root = _configure_queue(monkeypatch, tmp_path)
    install_root = extensions_root / "sample"
    install_root.mkdir()
    removed: list[Path] = []

    deletion_queue.add_pending_deletion("sample", install_root)
    deletion_queue.add_pending_deletion("sample", install_root)
    payload = json.loads((tmp_path / "pending.json").read_text(encoding="utf-8"))
    assert payload == [{"name": "sample", "path": str(install_root.resolve())}]

    deletion_queue.process_pending_deletions(removed.append)

    assert removed == [install_root.resolve()]
    assert not (tmp_path / "pending.json").exists()


def test_corrupt_queue_is_quarantined(monkeypatch, tmp_path: Path) -> None:
    _configure_queue(monkeypatch, tmp_path)
    queue_path = tmp_path / "pending.json"
    queue_path.write_text("not-json", encoding="utf-8")

    assert deletion_queue.get_pending_deletion_paths() == set()
    assert not queue_path.exists()
    assert len(list(tmp_path.glob("pending.json.corrupt.*"))) == 1


def test_concurrent_pending_deletions_do_not_lose_entries(monkeypatch, tmp_path: Path) -> None:
    extensions_root = _configure_queue(monkeypatch, tmp_path)
    roots = [extensions_root / f"extension-{index}" for index in range(8)]
    for root in roots:
        root.mkdir()

    def add(root: Path) -> None:
        deletion_queue.add_pending_deletion(root.name, root)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(add, roots))

    assert deletion_queue.get_pending_deletion_paths() == {
        root.resolve() for root in roots
    }
