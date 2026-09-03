from __future__ import annotations

import contextlib
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from src.logger import logger

import config

_PROCESS_LOCK = threading.RLock()


def _pending_deletions_file() -> Path:
    return Path(config.EXTENSIONS.PENDING_DELETIONS_FILE)


def _extensions_root() -> Path:
    return Path(config.EXTENSIONS.EXTENSIONS_DATA_DIR).resolve()


@contextmanager
def _locked_queue() -> Iterator[None]:
    queue_path = _pending_deletions_file()
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = queue_path.with_suffix(f"{queue_path.suffix}.lock")
    with _PROCESS_LOCK, lock_path.open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file, fcntl.LOCK_UN)


def _quarantine_corrupt_file(file_path: Path) -> None:
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = file_path.with_name(f"{file_path.name}.corrupt.{suffix}")
    try:
        file_path.replace(target)
    except OSError:
        logger.exception("Failed to quarantine corrupt extension deletion queue '{}'", file_path)
    else:
        logger.error("Corrupt extension deletion queue moved to '{}'", target)


def _validate_path(path: str | Path) -> Path:
    resolved = Path(path).resolve()
    root = _extensions_root()
    if resolved == root or resolved.parent != root:
        raise ValueError(f"Extension deletion path must be a direct child of '{root}': '{resolved}'")
    return resolved


def _load_entries_unlocked() -> list[dict[str, str]]:
    file_path = _pending_deletions_file()
    if not file_path.exists():
        return []
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to read pending extensions deletions from '{}'", file_path)
        _quarantine_corrupt_file(file_path)
        return []
    if not isinstance(payload, list):
        logger.error("Pending extensions deletions file '{}' has unexpected format", file_path)
        _quarantine_corrupt_file(file_path)
        return []

    entries: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        path = item.get("path")
        if not isinstance(name, str) or not isinstance(path, str):
            continue
        try:
            normalized_path = _validate_path(path)
        except ValueError as exc:
            logger.error("Ignoring unsafe pending extension deletion: {}", exc)
            continue
        entries.append({"name": name, "path": str(normalized_path)})
    return entries


def _load_entries() -> list[dict[str, str]]:
    with _locked_queue():
        return _load_entries_unlocked()


def _save_entries_unlocked(entries: list[dict[str, str]]) -> None:
    file_path = _pending_deletions_file()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(
        f".{file_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        with tmp_path.open("w", encoding="utf-8") as stream:
            json.dump(entries, stream, ensure_ascii=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        tmp_path.replace(file_path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()


def add_pending_deletion(name: str, path: Path) -> None:
    normalized_path = str(_validate_path(path))
    with _locked_queue():
        entries = [
            item
            for item in _load_entries_unlocked()
            if item["name"] != name and item["path"] != normalized_path
        ]
        entries.append({"name": name, "path": normalized_path})
        _save_entries_unlocked(entries)
    logger.warning(
        "Extension '{}' scheduled for deferred deletion after restart: '{}'",
        name,
        normalized_path,
    )


def get_pending_deletion_paths() -> set[Path]:
    return {Path(item["path"]) for item in _load_entries()}


def process_pending_deletions(remove_dir) -> None:
    with _locked_queue():
        remaining: list[dict[str, str]] = []
        for item in _load_entries_unlocked():
            install_root = Path(item["path"])
            if not install_root.exists():
                logger.info(
                    "Deferred extension deletion already completed for '{}' at '{}'",
                    item["name"],
                    install_root,
                )
                continue
            try:
                remove_dir(install_root)
                logger.info(
                    "Deferred extension deletion completed for '{}' at '{}'",
                    item["name"],
                    install_root,
                )
            except Exception:
                logger.exception(
                    "Deferred extension deletion is still blocked for '{}' at '{}'",
                    item["name"],
                    install_root,
                )
                remaining.append(item)

        file_path = _pending_deletions_file()
        if remaining:
            _save_entries_unlocked(remaining)
        elif file_path.exists():
            file_path.unlink()
