import threading
from pathlib import Path

from src.extensions._runtime_lock import RUNTIME_LOCK
from src.types import ExtensionManifest


class RegisteredExtension(ExtensionManifest):
    root_dir: Path
    manifest_path: Path


_REGISTRY_LOCK = threading.RLock()
_EXTENSIONS: dict[str, RegisteredExtension] = {}


def add(extension: RegisteredExtension) -> None:
    with RUNTIME_LOCK, _REGISTRY_LOCK:
        _EXTENSIONS[extension.name] = extension


def get(name: str) -> RegisteredExtension | None:
    with RUNTIME_LOCK, _REGISTRY_LOCK:
        return _EXTENSIONS.get(name)


def get_all() -> dict[str, RegisteredExtension]:
    with RUNTIME_LOCK, _REGISTRY_LOCK:
        return _EXTENSIONS.copy()


def clear() -> None:
    with RUNTIME_LOCK, _REGISTRY_LOCK:
        _EXTENSIONS.clear()


def replace_all(extensions: dict[str, RegisteredExtension]) -> None:
    with RUNTIME_LOCK, _REGISTRY_LOCK:
        _EXTENSIONS.clear()
        _EXTENSIONS.update(extensions)
