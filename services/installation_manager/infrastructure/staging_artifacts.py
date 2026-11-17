"""Private immutable staging files and selected instance configuration."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID, uuid4

from ..domain.operation_state import ArtifactKind, FailureReason
from ..domain.release_manifest import StagingError, canonical_json, strict_json
from .operation_files import (
    _require_private,
    _require_regular_file,
    prepare_directory,
    sync_directory,
)
from .operation_store import OperationStore

MAX_CONFIG_BYTES = 256 * 1024
CONFIG_KEY = re.compile(
    r"(?:DVT_[A-Z0-9_]+|PROJECT_SCHEDULER_(?:HOST|PORT)|CONTAINER_REGISTRY_URL|RAW_STORAGE_URL|COMPOSE_PROFILES)"
)


def artifact_directory(store: OperationStore, kind: ArtifactKind, artifact_id: UUID) -> Path:
    path = store.artifact_path(kind, artifact_id)
    for directory in (path.parent.parent, path.parent, path):
        prepare_directory(directory)
    return path


def read_artifact(path: Path, limit: int) -> bytes | None:
    try:
        if not path.exists() and not path.is_symlink():
            return None
        _require_regular_file(path.lstat())
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Artifact too large")
    except (PermissionError, ValueError):
        raise StagingError(
            FailureReason.INVALID_PACKAGE,
            "An artifact has invalid permissions, type or size",
            "Check the owner and integrity of the protected artifact",
        ) from None
    else:
        return data


def write_artifact(path: Path, content: bytes) -> None:
    current = read_artifact(path, len(content))
    if current is not None:
        if current != content:
            raise StagingError(
                FailureReason.INVALID_PACKAGE,
                "A staging artifact conflicts with an immutable saved file",
                "Investigate the conflict before continuing the same operation",
            )
        return
    fd, name = tempfile.mkstemp(prefix=".partial-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Staging is written under the executor lock; configuration uses a fresh UUID.
        Path(name).replace(path)
        sync_directory(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def validate_config(values: Mapping[str, str]) -> None:
    if not isinstance(values, dict) or any(
        not isinstance(key, str)
        or not CONFIG_KEY.fullmatch(key)
        or not isinstance(value, str)
        or any(char in value for char in "\n\r\0")
        for key, value in values.items()
    ):
        raise StagingError(
            FailureReason.COMPOSE,
            "The selected configuration contains an unsupported variable or value",
            "Use the supported instance configuration keys and single-line values",
        )


def save_config(store: OperationStore, values: dict[str, str]) -> UUID:
    validate_config(values)
    content = canonical_json(values)
    if len(content) > MAX_CONFIG_BYTES:
        raise ValueError("Instance configuration is too large")
    config_id = uuid4()
    directory = artifact_directory(store, ArtifactKind.CONFIG, config_id)
    write_artifact(directory / "values.json", content)
    return config_id


def load_config(store: OperationStore, config_id: UUID | None) -> dict[str, str]:
    try:
        if config_id is None:
            raise ValueError
        path = store.artifact_path(ArtifactKind.CONFIG, config_id)
        for directory in (path.parent.parent, path.parent, path):
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError
            _require_private(info, 0o700)
        content = read_artifact(path / "values.json", MAX_CONFIG_BYTES)
        if content is None:
            raise ValueError
        values = strict_json(content)
    except (FileNotFoundError, PermissionError, ValueError, json.JSONDecodeError, RecursionError):
        raise StagingError(
            FailureReason.COMPOSE,
            "The operation has no readable protected configuration",
            "Restore the admitted configuration by ID before continuing",
        ) from None
    validate_config(values)
    return values
