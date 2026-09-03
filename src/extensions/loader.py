from __future__ import annotations

import contextlib
import hashlib
import importlib
import re
import sys
import tomllib
import types
from collections.abc import Iterable, Iterator
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from src.extensions import registry as extensions_registry
from src.extensions.deletion_queue import get_pending_deletion_paths
from src.extensions.registry import RegisteredExtension
from src.logger import logger
from src.types import ExtensionManifest

import config


def _path_under_root(path: str | Path | None, root: Path) -> bool:
    if not path:
        return False
    try:
        Path(path).resolve().relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


@contextlib.contextmanager
def _temporary_sys_path(paths: Iterable[Path]) -> Iterator[None]:
    added: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        path_str = str(path.resolve())
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
            added.append(path_str)
    try:
        yield
    finally:
        for path_str in added:
            with contextlib.suppress(ValueError):
                sys.path.remove(path_str)


def _safe_extension_module_name(name: str) -> str:
    safe = re.sub(r"[^0-9a-zA-Z_]+", "_", (name or "").strip().lower()).strip("_")
    if not safe:
        safe = "ext"
    if safe[0].isdigit():
        safe = f"ext_{safe}"
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"{safe}_{digest}"


def extension_module_prefix(name: str) -> str:
    return f"dvt_extensions.{_safe_extension_module_name(name)}"


def _ensure_namespace_package(name: str, paths: Iterable[Path]) -> types.ModuleType:
    resolved_paths = [str(path.resolve()) for path in paths]
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        module.__package__ = name
        module.__path__ = resolved_paths
        sys.modules[name] = module
        return module

    module.__path__ = resolved_paths
    return module


def _ensure_extension_namespace(extension: RegisteredExtension, nodes_dir: Path) -> str:
    base_name = "dvt_extensions"
    _ensure_namespace_package(base_name, [])
    extension_prefix = extension_module_prefix(extension.name)
    _ensure_namespace_package(extension_prefix, [extension.root_dir])
    _ensure_namespace_package(f"{extension_prefix}.nodes", [nodes_dir])
    return f"{extension_prefix}.nodes"


def ensure_extension_root_namespace(extension: RegisteredExtension) -> str:
    """Create the isolated package namespace used by all extension capabilities."""
    _ensure_namespace_package("dvt_extensions", [])
    extension_prefix = extension_module_prefix(extension.name)
    _ensure_namespace_package(extension_prefix, [extension.root_dir])
    return extension_prefix


def purge_extension_modules(extension: RegisteredExtension) -> None:
    prefix = extension_module_prefix(extension.name)
    root_dir = extension.root_dir.resolve()
    for module_name, module in list(sys.modules.items()):
        is_namespace_module = module_name == prefix or module_name.startswith(f"{prefix}.")
        module_file = getattr(module, "__file__", None)
        is_extension_file = _path_under_root(module_file, root_dir)
        if is_namespace_module or is_extension_file:
            sys.modules.pop(module_name, None)


def iter_extension_roots() -> list[Path]:
    extensions_dir = Path(config.EXTENSIONS.EXTENSIONS_DATA_DIR).resolve()
    if not extensions_dir.exists():
        return []

    pending_paths = {path.resolve() for path in get_pending_deletion_paths()}
    roots: list[Path] = []
    for path in extensions_dir.iterdir():
        if not path.is_dir():
            continue
        resolved = path.resolve()
        if not _path_under_root(resolved, extensions_dir):
            logger.error("Skipping extension root outside extensions directory: '{}'", path)
            continue
        if resolved in pending_paths:
            logger.info("Skipping extension directory pending deletion: '{}'", path)
            continue
        roots.append(path)
    return sorted(roots, key=lambda item: item.name.casefold())


def _get_project_url(urls: dict, *keys: str) -> str | None:
    for key in keys:
        value = urls.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def load_manifest_payload(root_dir: Path) -> ExtensionManifest | None:
    manifest_path = root_dir / config.EXTENSIONS.MANIFEST_FILE
    if not manifest_path.exists():
        logger.debug("Extension manifest not found in '{}'", root_dir)
        return None

    logger.debug("Loading extension manifest from '{}'", manifest_path)
    payload = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    project = payload.get("project") or {}
    tool = (payload.get("tool") or {}).get("dvt_extension") or {}
    if not tool:
        logger.debug("No [tool.dvt_extension] section in '{}'", manifest_path)
        return None
    urls = project.get("urls") or {}
    if not isinstance(urls, dict):
        raise TypeError(f"[project.urls] must be a table in '{manifest_path}'")
    manifest_payload = {
        "name": tool.get("name") or project.get("name") or "",
        "version": project.get("version") or "",
        "description": project.get("description") or "",
        "repository_url": _get_project_url(
            urls, "Repository", "repository", "Source", "source"
        ),
        "homepage_url": _get_project_url(urls, "Homepage", "homepage", "Home", "home"),
        "display_name": tool.get("display_name"),
        "dvt_version": tool.get("dvt_version"),
        "backend": tool.get("backend") or {},
        "frontend": tool.get("frontend"),
        "requirements": project.get("dependencies") or [],
        "state_schema": tool.get("state_schema") or {},
        "nodes": tool.get("nodes") or [],
    }
    return ExtensionManifest.model_validate(manifest_payload)


def load_manifest(root_dir: Path, extension_name: str | None = None) -> RegisteredExtension | None:
    manifest = load_manifest_payload(root_dir)
    if manifest is None:
        return None

    effective_name = extension_name or root_dir.name
    manifest_payload = manifest.model_dump()
    manifest_payload["name"] = effective_name
    backend_payload = dict(manifest_payload.get("backend") or {})
    # Legacy extensions historically relied on the conventional backend/nodes
    # directory even when nodes_dir was omitted from the manifest.
    if backend_payload.get("nodes_dir") is None and (root_dir / "backend" / "nodes").is_dir():
        backend_payload["nodes_dir"] = "backend/nodes"
    manifest_payload["backend"] = backend_payload
    return RegisteredExtension(
        **manifest_payload,
        root_dir=root_dir.resolve(),
        manifest_path=(root_dir / config.EXTENSIONS.MANIFEST_FILE).resolve(),
    )


def check_dvt_compatibility(manifest: ExtensionManifest) -> bool:
    if not config.APP.VERSION:
        return True
    if manifest.dvt_version is None or manifest.dvt_version == "*":
        return True

    try:
        compatible = SpecifierSet(manifest.dvt_version).contains(
            Version(config.APP.VERSION), prereleases=True
        )
    except Exception:
        logger.exception("Invalid DVT compatibility spec for extension '{}'", manifest.name)
        return False

    if not compatible:
        logger.warning(
            "Extension '{}' v{} requires DVT {}, but current DVT version is {}",
            manifest.name,
            manifest.version,
            manifest.dvt_version,
            config.APP.VERSION,
        )
    return compatible


def _effective_nodes_dir_value(extension: RegisteredExtension) -> str | None:
    configured = extension.backend.nodes_dir
    if configured is not None:
        return configured or None

    legacy_nodes_dir = extension.root_dir / "backend" / "nodes"
    if legacy_nodes_dir.is_dir():
        return "backend/nodes"
    return None


def resolve_nodes_dir_if_present(extension: RegisteredExtension) -> Path | None:
    nodes_dir_value = _effective_nodes_dir_value(extension)
    if not nodes_dir_value:
        return None
    raw_nodes_dir = Path(nodes_dir_value)
    if raw_nodes_dir.is_absolute():
        raise ValueError(f"Extension '{extension.name}' nodes_dir must be relative")
    nodes_dir = (extension.root_dir / raw_nodes_dir).resolve()
    if not _path_under_root(nodes_dir, extension.root_dir):
        raise ValueError(f"Extension '{extension.name}' nodes_dir escapes extension root")
    if not nodes_dir.is_dir():
        raise FileNotFoundError(
            f"Extension '{extension.name}' nodes dir does not exist: {nodes_dir}"
        )
    return nodes_dir


def resolve_nodes_dir(extension: RegisteredExtension) -> Path:
    nodes_dir = resolve_nodes_dir_if_present(extension)
    if nodes_dir is None:
        raise ValueError(f"Extension '{extension.name}' does not declare nodes_dir")
    return nodes_dir


def backend_package_name(extension: RegisteredExtension) -> str:
    nodes_dir_value = _effective_nodes_dir_value(extension)
    if not nodes_dir_value:
        raise ValueError(f"Extension '{extension.name}' does not declare nodes_dir")
    raw_nodes_dir = Path(nodes_dir_value)
    resolve_nodes_dir(extension)
    if not raw_nodes_dir.parts:
        raise ValueError(f"Extension '{extension.name}' has invalid nodes_dir")
    package_name = raw_nodes_dir.parts[0]
    if not package_name.isidentifier():
        raise ValueError(
            f"Extension '{extension.name}' backend package '{package_name}' is not importable"
        )
    return package_name


def init_extensions() -> dict[str, RegisteredExtension]:
    loaded: dict[str, RegisteredExtension] = {}
    if not config.EXTENSIONS.ENABLED:
        extensions_registry.replace_all({})
        logger.info("Extensions are disabled by config.")
        return loaded

    for root_dir in iter_extension_roots():
        try:
            extension = load_manifest(root_dir, extension_name=root_dir.name)
            if extension is None or not check_dvt_compatibility(extension):
                continue
            resolve_nodes_dir_if_present(extension)
            loaded[extension.name] = extension
        except Exception:
            logger.exception("Failed to load extension manifest from {}", root_dir)

    extensions_registry.replace_all(loaded)
    logger.info("Loaded {} extension manifests.", len(loaded))
    return loaded


def import_extension_nodes_for(
    extension: RegisteredExtension,
    *,
    purge_modules_before_import: bool = True,
) -> dict[str, object]:
    if not config.EXTENSIONS.AUTOLOAD:
        return {}

    from src.node_dsl._init_nodes import import_nodes

    nodes_dir = resolve_nodes_dir_if_present(extension)
    if nodes_dir is None:
        return {}
    if purge_modules_before_import:
        purge_extension_modules(extension)
    module_prefix = _ensure_extension_namespace(extension, nodes_dir)
    with _temporary_sys_path([extension.root_dir]):
        return import_nodes(nodes_dir, module_prefix=module_prefix)


def import_extension_nodes() -> dict[str, object]:
    importlib.invalidate_caches()
    imported_modules: dict[str, object] = {}
    if not config.EXTENSIONS.AUTOLOAD:
        logger.debug("Extensions autoload is disabled by config.")
        return imported_modules

    for extension in extensions_registry.get_all().values():
        try:
            modules = import_extension_nodes_for(extension)
            imported_modules.update(modules)
            logger.debug(
                "Imported extension modules for '{}' count={}", extension.name, len(modules)
            )
        except Exception:
            logger.exception("Failed to import nodes from extension '{}'", extension.name)
    return imported_modules
