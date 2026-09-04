from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from .types import NodePackageManifest


class NodePackageManifestError(ValueError):
    pass


def load_node_package_manifest(path: Path) -> NodePackageManifest:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NodePackageManifestError(f"Cannot read node manifest '{path}': {exc}") from exc

    try:
        payload = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise NodePackageManifestError(f"Invalid YAML in node manifest '{path}': {exc}") from exc

    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise NodePackageManifestError(
            f"Node manifest '{path}' must contain a YAML mapping, got {type(payload).__name__}"
        )

    try:
        return NodePackageManifest.model_validate(payload)
    except ValidationError as exc:
        raise NodePackageManifestError(f"Invalid node manifest '{path}': {exc}") from exc
