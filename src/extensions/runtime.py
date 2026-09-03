from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

from src.extensions import registry as extensions_registry
from src.extensions._runtime_lock import RUNTIME_LOCK
from src.extensions.loader import (
    backend_package_name,
    check_dvt_compatibility,
    import_extension_nodes_for,
    iter_extension_roots,
    load_manifest,
    purge_extension_modules,
    resolve_nodes_dir_if_present,
)
from src.extensions.registry import RegisteredExtension
from src.logger import logger

import config


@dataclass(frozen=True)
class ExtensionRuntimeSpec:
    name: str
    root_dir: Path


@dataclass(frozen=True)
class ExtensionLoadFailure:
    extension_name: str
    stage: str
    message: str


@dataclass
class ExtensionLoadReport:
    loaded: dict[str, RegisteredExtension] = field(default_factory=dict)
    failures: dict[str, ExtensionLoadFailure] = field(default_factory=dict)
    skipped: set[str] = field(default_factory=set)


class ExtensionRuntimeLoadError(RuntimeError):
    def __init__(self, failure: ExtensionLoadFailure):
        self.failure = failure
        super().__init__(failure.message)


_ACTIVE_SPECS: dict[str, ExtensionRuntimeSpec] = {}


@dataclass(frozen=True)
class _RuntimeModulesSnapshot:
    modules: dict[str, ModuleType]
    roots: tuple[Path, ...]


def _module_is_owned_by_runtime(
    module_name: str, module: object, roots: tuple[Path, ...]
) -> bool:
    if module_name == "dvt_extensions" or module_name.startswith("dvt_extensions."):
        return True
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return False
    try:
        resolved_file = Path(module_file).resolve()
    except (OSError, RuntimeError, ValueError, TypeError):
        return False
    for root in roots:
        try:
            resolved_file.relative_to(root)
        except ValueError:
            continue
        return True
    return False


def _snapshot_runtime_modules(
    specs: tuple[ExtensionRuntimeSpec, ...] | None,
) -> _RuntimeModulesSnapshot:
    roots = {
        extension.root_dir.resolve() for extension in extensions_registry.get_all().values()
    }
    if specs is not None:
        roots.update(spec.root_dir.resolve() for spec in specs)
    normalized_roots = tuple(sorted(roots, key=lambda path: str(path).casefold()))
    modules = {
        name: module
        for name, module in sys.modules.items()
        if isinstance(module, ModuleType)
        and _module_is_owned_by_runtime(name, module, normalized_roots)
    }
    return _RuntimeModulesSnapshot(modules=modules, roots=normalized_roots)


def _restore_runtime_modules(snapshot: _RuntimeModulesSnapshot) -> None:
    for module_name, module in list(sys.modules.items()):
        if _module_is_owned_by_runtime(module_name, module, snapshot.roots):
            sys.modules.pop(module_name, None)
    sys.modules.update(snapshot.modules)


def _default_specs() -> list[ExtensionRuntimeSpec]:
    return [ExtensionRuntimeSpec(name=root.name, root_dir=root) for root in iter_extension_roots()]


def _record_failure(
    report: ExtensionLoadReport,
    extension_name: str,
    stage: str,
    exc: BaseException | str,
) -> None:
    message = str(exc)
    report.failures[extension_name] = ExtensionLoadFailure(
        extension_name=extension_name,
        stage=stage,
        message=message,
    )
    logger.error(
        "Extension runtime load failed name='{}' stage='{}': {}",
        extension_name,
        stage,
        message,
    )


def _validate_backend_packages(
    extensions: dict[str, RegisteredExtension], report: ExtensionLoadReport
) -> None:
    package_owners: dict[str, list[str]] = {}
    for extension_name, extension in extensions.items():
        try:
            if resolve_nodes_dir_if_present(extension) is None:
                continue
            package_name = backend_package_name(extension)
        except Exception as exc:
            _record_failure(report, extension_name, "backend_package", exc)
            continue
        package_owners.setdefault(package_name, []).append(extension_name)
        try:
            existing_spec = importlib.util.find_spec(package_name)
        except (ImportError, AttributeError, ValueError) as exc:
            _record_failure(
                report,
                extension_name,
                "backend_package",
                f"Cannot inspect backend package '{package_name}': {exc}",
            )
            continue
        if existing_spec is not None and not _spec_belongs_to_extension(
            existing_spec, extension.root_dir
        ):
            _record_failure(
                report,
                extension_name,
                "backend_package",
                f"Backend package '{package_name}' conflicts with an existing Python package",
            )

    for package_name, owners in package_owners.items():
        if len(owners) < 2:
            continue
        joined = ", ".join(sorted(owners))
        for extension_name in owners:
            _record_failure(
                report,
                extension_name,
                "backend_package",
                f"Backend package '{package_name}' is shared by extensions: {joined}",
            )


def _spec_belongs_to_extension(spec, root_dir: Path) -> bool:
    candidates: list[str] = []
    if spec.origin and spec.origin not in {"built-in", "frozen"}:
        candidates.append(spec.origin)
    if spec.submodule_search_locations:
        candidates.extend(spec.submodule_search_locations)
    if not candidates:
        return False
    root = root_dir.resolve()
    for candidate in candidates:
        try:
            Path(candidate).resolve().relative_to(root)
        except (OSError, RuntimeError, ValueError):
            return False
    return True


def _load_all_extension_runtimes_locked(
    specs: Iterable[ExtensionRuntimeSpec] | None = None,
    *,
    strict_extension_names: frozenset[str] = frozenset(),
    preloaded_extension_names: frozenset[str] = frozenset(),
) -> ExtensionLoadReport:
    from src.node_dsl._init_nodes import rebuild_node_registries

    normalized_specs = sorted(
        _default_specs() if specs is None else specs, key=lambda item: item.name.casefold()
    )
    if not config.EXTENSIONS.ENABLED:
        normalized_specs = []

    with RUNTIME_LOCK:
        report = ExtensionLoadReport()
        manifests: dict[str, RegisteredExtension] = {}

        for spec in normalized_specs:
            try:
                root_dir = spec.root_dir.resolve()
                extensions_root = Path(config.EXTENSIONS.EXTENSIONS_DATA_DIR).resolve()
                if root_dir.parent != extensions_root:
                    raise ValueError(
                        f"Extension root must be a direct child of '{extensions_root}': "
                        f"'{root_dir}'"
                    )
                extension = load_manifest(root_dir, extension_name=spec.name)
                if extension is None:
                    raise ValueError(f"Manifest not found in '{spec.root_dir}'")
                if not check_dvt_compatibility(extension):
                    raise ValueError(
                        f"Extension '{spec.name}' is incompatible with DVT {config.APP.VERSION}"
                    )
                resolve_nodes_dir_if_present(extension)
                manifests[spec.name] = extension
            except Exception as exc:
                _record_failure(report, spec.name, "manifest", exc)

        _validate_backend_packages(manifests, report)
        for failed_name in report.failures:
            manifests.pop(failed_name, None)

        previous_extensions = extensions_registry.get_all()
        requested_names = {spec.name for spec in normalized_specs}
        report.skipped = set(previous_extensions).difference(requested_names)
        for extension_name, extension in previous_extensions.items():
            if extension_name not in manifests:
                purge_extension_modules(extension)

        modules_by_extension: dict[str, dict[str, ModuleType]] = {}
        for extension_name, extension in manifests.items():
            try:
                modules = import_extension_nodes_for(
                    extension,
                    purge_modules_before_import=extension_name not in preloaded_extension_names,
                )
                modules_by_extension[extension_name] = {
                    name: module for name, module in modules.items() if isinstance(module, ModuleType)
                }
            except Exception as exc:
                _record_failure(report, extension_name, "import", exc)
                purge_extension_modules(extension)

        strict_failure_names = strict_extension_names.intersection(report.failures)
        if strict_failure_names:
            raise ExtensionRuntimeLoadError(
                report.failures[sorted(strict_failure_names)[0]]
            )

        for failed_name in report.failures:
            manifests.pop(failed_name, None)
            modules_by_extension.pop(failed_name, None)

        try:
            rebuild_result = rebuild_node_registries(
                extension_modules=modules_by_extension,
                extensions=manifests,
                strict_extension_names=strict_extension_names,
            )
        except ExtensionRuntimeLoadError:
            raise
        except Exception as exc:
            strict_name = next(iter(strict_extension_names), "<runtime>")
            failure = ExtensionLoadFailure(strict_name, "registry", str(exc))
            if strict_extension_names:
                raise ExtensionRuntimeLoadError(failure) from exc
            raise

        for extension_name, message in rebuild_result.extension_failures.items():
            _record_failure(report, extension_name, "node_registry", message)
            extension = manifests.pop(extension_name, None)
            modules_by_extension.pop(extension_name, None)
            if extension is not None:
                purge_extension_modules(extension)

        report.loaded = manifests
        extensions_registry.replace_all(manifests)
        _ACTIVE_SPECS.clear()
        _ACTIVE_SPECS.update(
            {spec.name: spec for spec in normalized_specs if spec.name in report.loaded}
        )

        logger.info(
            "Extension runtime refresh completed: loaded={} failed={} skipped={}",
            len(report.loaded),
            len(report.failures),
            len(report.skipped),
        )
        return report


def load_all_extension_runtimes(
    specs: Iterable[ExtensionRuntimeSpec] | None = None,
    *,
    strict_extension_names: frozenset[str] = frozenset(),
    preloaded_extension_names: frozenset[str] = frozenset(),
) -> ExtensionLoadReport:
    normalized_specs = tuple(_default_specs()) if specs is None else tuple(specs)
    with RUNTIME_LOCK:
        module_snapshot = _snapshot_runtime_modules(normalized_specs)
        try:
            return _load_all_extension_runtimes_locked(
                normalized_specs,
                strict_extension_names=strict_extension_names,
                preloaded_extension_names=preloaded_extension_names,
            )
        except Exception:
            _restore_runtime_modules(module_snapshot)
            raise


def load_extension_runtime(
    root_dir: Path, extension_name: str | None = None
) -> RegisteredExtension | None:
    name = extension_name or root_dir.name
    specs = dict(_ACTIVE_SPECS)
    specs[name] = ExtensionRuntimeSpec(name=name, root_dir=root_dir)
    report = load_all_extension_runtimes(
        specs.values(), strict_extension_names=frozenset({name})
    )
    return report.loaded.get(name)
