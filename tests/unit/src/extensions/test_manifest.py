from src.extensions.loader import load_manifest
from src.extensions.manifest import ExtensionManifest


def test_extension_manifest_defaults():
    manifest = ExtensionManifest(name="b24", version="0.1.0")

    assert manifest.backend.nodes_dir is None
    assert manifest.backend.gateway_entrypoint is None
    assert manifest.backend.migrations_dir is None
    assert manifest.frontend is None
    assert manifest.requirements == []
    assert manifest.state_schema == {}
    assert manifest.nodes == []


def test_load_manifest_uses_nodes_from_pyproject(tmp_path):
    extension_root = tmp_path / "b24"
    extension_root.mkdir(parents=True)
    (extension_root / "pyproject.toml").write_text(
        """
        [project]
        name = "b24"
        version = "0.1.0"
        description = "Bitrix24"
        dependencies = ["httpx>=0.28"]

        [tool.dvt_extension]
        name = "b24"

        [[tool.dvt_extension.nodes]]
        name = "SampleNode"
        display_name = "Sample Title"
        description = "Short node description"
        """,
        encoding="utf-8",
    )

    manifest = load_manifest(extension_root)

    assert manifest is not None
    assert manifest.requirements == ["httpx>=0.28"]
    assert [item.model_dump() for item in manifest.nodes] == [
        {
            "name": "SampleNode",
            "display_name": "Sample Title",
            "description": "Short node description",
        }
    ]


def test_load_manifest_uses_extension_root_name_as_effective_name(tmp_path):
    extension_root = tmp_path / "custom_alias"
    extension_root.mkdir(parents=True)
    (extension_root / "pyproject.toml").write_text(
        """
        [project]
        name = "git_manifest_name"
        version = "0.1.0"

        [tool.dvt_extension]
        name = "git_manifest_name"
        """,
        encoding="utf-8",
    )

    manifest = load_manifest(extension_root, extension_name=extension_root.name)

    assert manifest is not None
    assert manifest.name == "custom_alias"


def test_load_manifest_keeps_legacy_conventional_backend_nodes(tmp_path):
    extension_root = tmp_path / "legacy"
    (extension_root / "backend" / "nodes").mkdir(parents=True)
    (extension_root / "pyproject.toml").write_text(
        """
        [project]
        name = "legacy"
        version = "1.0.0"

        [tool.dvt_extension]
        name = "legacy"
        """,
        encoding="utf-8",
    )

    manifest = load_manifest(extension_root)

    assert manifest is not None
    assert manifest.backend.nodes_dir == "backend/nodes"


def test_load_manifest_allows_gateway_only_extension(tmp_path):
    extension_root = tmp_path / "gateway-only"
    extension_root.mkdir(parents=True)
    (extension_root / "pyproject.toml").write_text(
        """
        [project]
        name = "gateway-only"
        version = "1.0.0"

        [tool.dvt_extension]
        name = "gateway-only"

        [tool.dvt_extension.backend]
        gateway_entrypoint = "backend.gateway:router"
        """,
        encoding="utf-8",
    )

    manifest = load_manifest(extension_root)

    assert manifest is not None
    assert manifest.backend.nodes_dir is None
    assert manifest.backend.gateway_entrypoint == "backend.gateway:router"


def test_extension_manifest_frontend_defaults():
    manifest = ExtensionManifest.model_validate(
        {
            "name": "b24",
            "version": "0.1.0",
            "frontend": {},
        }
    )

    assert manifest.frontend is not None
    assert manifest.frontend.dist_dir == "frontend/dist"
    assert manifest.frontend.entry_file == "index.js"
