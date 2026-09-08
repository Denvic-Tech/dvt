from pathlib import Path

import pytest

from src.node_dsl.discovery.manifests import (
    NodePackageManifestError,
    load_node_package_manifest,
)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "node.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_manifest_accepts_v1(tmp_path: Path) -> None:
    manifest = load_node_package_manifest(_write(tmp_path, "schema_version: 1\n"))
    assert manifest.schema_version == 1


@pytest.mark.parametrize(
    "content",
    [
        "schema_version: [\n",
        "{}\n",
        "schema_version: 2\n",
        "schema_version: 1\nunknown: true\n",
    ],
)
def test_manifest_rejects_invalid_v1_contract(tmp_path: Path, content: str) -> None:
    with pytest.raises(NodePackageManifestError, match=r"node\.yaml"):
        load_node_package_manifest(_write(tmp_path, content))
