"""Validate the form before the bootstrap host commits to a data directory."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException

from core.operator_contract import InstallRequest

from ..domain.operation_state import _public_origin
from ..domain.release_manifest import canonical_json, strict_json
from ..host_bootstrap import atomic_write
from ..infrastructure.staging_artifacts import read_artifact

INTENT = "install-intent.json"
MAX_INTENT_BYTES = 32 * 1024


def normalized_request(payload: InstallRequest, config: dict) -> InstallRequest:
    temporary = config.get("wizard_temporary")
    directory = payload.install_dir
    if directory is not None:
        directory = posixpath.normpath(directory)
        if (
            not re.fullmatch(r"/[a-zA-Z0-9_./-]+", directory)
            or directory.startswith("//") or ".." in payload.install_dir.split("/")
        ):
            raise HTTPException(422, "Укажите абсолютный путь к каталогу установки.")
        if not temporary and directory != config["data"]:
            raise HTTPException(422, "Каталог этого экземпляра уже выбран.")
    urls = payload.public_urls
    if urls is not None:
        origins = []
        for value in urls:
            try:
                origin = _public_origin(value)
                if payload.app_port is not None and (temporary or config.get("manager_origins")):
                    parts = urlsplit(origin)
                    host = parts.hostname
                    if ":" in host:
                        host = f"[{host}]"
                    origin = _public_origin(f"{parts.scheme}://{host}:{payload.app_port}")
            except ValueError:
                raise HTTPException(422, "Укажите адрес DVT с http:// или https://.") from None
            if origin not in origins:
                origins.append(origin)
        urls = origins
        if not temporary and urls[0] != config["public_url"]:
            raise HTTPException(422, "Основной адрес этого экземпляра уже выбран.")
    if temporary:
        if not directory or not urls:
            raise HTTPException(422, "Укажите путь установки и адрес DVT.")
        if payload.app_port == config["port"]:
            raise HTTPException(422, "Этот порт уже используется мастером установки.")
    return payload.model_copy(update={"install_dir": directory, "public_urls": urls})


def pending_intent(control: Path) -> dict | None:
    raw = read_artifact(control / INTENT, MAX_INTENT_BYTES)
    return strict_json(raw) if raw is not None else None


def request_directory(control: Path, key: str, intent: dict) -> None:
    """Called under the admission lock. The host consumes the atomically published request."""
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", key):
        raise HTTPException(422, "Invalid idempotency key")
    saved = pending_intent(control)
    proposed = {"key": key, "request": intent}
    error = read_artifact(control / "install-error.json", MAX_INTENT_BYTES)
    rejected = strict_json(error) if error else {}
    if rejected.get("key") == key:
        raise HTTPException(422, rejected["detail"])
    if saved and saved != proposed and saved["key"] != rejected.get("key"):
        raise HTTPException(409, "Установка уже запущена.")
    if saved != proposed:
        atomic_write(control / INTENT, canonical_json(proposed))
    raise HTTPException(503, "Setup is switching to the installation directory")
