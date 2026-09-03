import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.extensions import loader, registry, runtime
from src.extensions.runtime import ExtensionRuntimeLoadError, ExtensionRuntimeSpec
from src.node_dsl._init_nodes import discover_node_classes


@pytest.fixture(autouse=True)
def _configure_extensions_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runtime.config.EXTENSIONS, "EXTENSIONS_DATA_DIR", tmp_path)


def _write_extension(
    root: Path, *, node_source: str | None = None, backend_name: str = "backend"
) -> None:
    nodes_dir = root / backend_name / "nodes"
    nodes_dir.mkdir(parents=True)
    (root / backend_name / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f"""
[project]
name = "sample"
version = "1.0.0"

[tool.dvt_extension]
name = "sample"

[tool.dvt_extension.backend]
nodes_dir = "{backend_name}/nodes"
""",
        encoding="utf-8",
    )
    (nodes_dir / "sample.py").write_text(
        node_source
        or """
from src.node_dsl.base_node.base import BaseNode

class RuntimeSampleNode(BaseNode):
    def process(self):
        return None
""",
        encoding="utf-8",
    )


def test_src_extensions_imports_in_clean_process() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "import src.extensions"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_safe_module_names_do_not_collide() -> None:
    assert loader.extension_module_prefix("foo-bar") != loader.extension_module_prefix("foo_bar")


def test_repeated_import_discovers_only_current_generation(monkeypatch, tmp_path: Path) -> None:
    extension_root = tmp_path / "sample"
    _write_extension(extension_root)
    extension = loader.load_manifest(extension_root, extension_name="sample")
    assert extension is not None

    monkeypatch.setattr(loader.config.EXTENSIONS, "AUTOLOAD", True)
    first_modules = loader.import_extension_nodes_for(extension)
    first_class = next(iter(first_modules.values())).RuntimeSampleNode
    second_modules = loader.import_extension_nodes_for(extension)
    second_class = next(iter(second_modules.values())).RuntimeSampleNode

    discovered = discover_node_classes(second_modules, extensions={"sample": extension})

    assert first_class is not second_class
    assert [item for item in discovered if item.__name__ == "RuntimeSampleNode"] == [second_class]
    assert str(extension_root.resolve()) not in sys.path
    loader.purge_extension_modules(extension)


def test_runtime_calls_import_once_for_one_extension(monkeypatch, tmp_path: Path) -> None:
    extension_root = tmp_path / "sample"
    _write_extension(extension_root)
    calls: list[str] = []

    def fake_import(extension, *, purge_modules_before_import=True):
        assert purge_modules_before_import is True
        calls.append(extension.name)
        return {}

    monkeypatch.setattr(runtime, "import_extension_nodes_for", fake_import)
    monkeypatch.setattr(
        "src.node_dsl._init_nodes.rebuild_node_registries",
        lambda **_kwargs: SimpleNamespace(extension_failures={}),
    )
    monkeypatch.setattr(runtime.config.APP, "VERSION", "")

    report = runtime.load_all_extension_runtimes(
        [ExtensionRuntimeSpec(name="sample", root_dir=extension_root)]
    )

    assert calls == ["sample"]
    assert list(report.loaded) == ["sample"]
    registry.clear()


def test_broken_extension_isolated_in_bulk_and_strict_for_target(
    monkeypatch, tmp_path: Path
) -> None:
    extension_root = tmp_path / "sample"
    _write_extension(extension_root, node_source="this is not valid python !!!")
    monkeypatch.setattr(runtime.config.APP, "VERSION", "")
    monkeypatch.setattr(
        "src.node_dsl._init_nodes.rebuild_node_registries",
        lambda **_kwargs: SimpleNamespace(extension_failures={}),
    )
    spec = ExtensionRuntimeSpec(name="sample", root_dir=extension_root)

    report = runtime.load_all_extension_runtimes([spec])

    assert report.loaded == {}
    assert report.failures["sample"].stage == "import"
    with pytest.raises(ExtensionRuntimeLoadError):
        runtime.load_all_extension_runtimes(
            [spec], strict_extension_names=frozenset({"sample"})
        )


def test_strict_refresh_restores_previous_modules_on_failure(
    monkeypatch, tmp_path: Path
) -> None:
    extension_root = tmp_path / "sample"
    _write_extension(extension_root)
    monkeypatch.setattr(runtime.config.APP, "VERSION", "")
    monkeypatch.setattr(
        "src.node_dsl._init_nodes.rebuild_node_registries",
        lambda **_kwargs: SimpleNamespace(extension_failures={}),
    )
    spec = ExtensionRuntimeSpec(name="sample", root_dir=extension_root)
    runtime.load_all_extension_runtimes([spec])
    prefix = loader.extension_module_prefix("sample")
    previous_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == prefix or name.startswith(f"{prefix}.")
    }
    (extension_root / "backend" / "nodes" / "sample.py").write_text(
        "this is not valid python !!!", encoding="utf-8"
    )

    with pytest.raises(ExtensionRuntimeLoadError):
        runtime.load_all_extension_runtimes(
            [spec], strict_extension_names=frozenset({"sample"})
        )

    assert previous_modules
    assert all(sys.modules.get(name) is module for name, module in previous_modules.items())
    extension = registry.get("sample")
    assert extension is not None
    loader.purge_extension_modules(extension)
    registry.clear()


def test_shared_backend_package_rejects_both_extensions(monkeypatch, tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    _write_extension(first_root, backend_name="shared_backend")
    _write_extension(second_root, backend_name="shared_backend")
    monkeypatch.setattr(runtime.config.APP, "VERSION", "")
    monkeypatch.setattr(
        "src.node_dsl._init_nodes.rebuild_node_registries",
        lambda **_kwargs: SimpleNamespace(extension_failures={}),
    )

    report = runtime.load_all_extension_runtimes(
        [
            ExtensionRuntimeSpec(name="first", root_dir=first_root),
            ExtensionRuntimeSpec(name="second", root_dir=second_root),
        ]
    )

    assert report.loaded == {}
    assert set(report.failures) == {"first", "second"}
    assert {failure.stage for failure in report.failures.values()} == {"backend_package"}


def test_existing_python_package_rejects_extension_backend(
    monkeypatch, tmp_path: Path
) -> None:
    extension_root = tmp_path / "sample"
    _write_extension(extension_root, backend_name="json")
    monkeypatch.setattr(runtime.config.APP, "VERSION", "")
    monkeypatch.setattr(
        "src.node_dsl._init_nodes.rebuild_node_registries",
        lambda **_kwargs: SimpleNamespace(extension_failures={}),
    )

    report = runtime.load_all_extension_runtimes(
        [ExtensionRuntimeSpec(name="sample", root_dir=extension_root)]
    )

    assert report.loaded == {}
    assert report.failures["sample"].stage == "backend_package"
