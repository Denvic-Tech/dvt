from __future__ import annotations

import copy
import hashlib
import importlib
import re
from collections import ChainMap
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette._utils import get_route_path
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocketClose

from src.extensions._runtime_lock import RUNTIME_LOCK
from src.extensions.loader import (
    _temporary_sys_path,
    check_dvt_compatibility,
    ensure_extension_root_namespace,
    load_manifest,
    purge_extension_modules,
)
from src.extensions.registry import RegisteredExtension
from src.extensions.runtime import ExtensionLoadFailure, ExtensionRuntimeSpec

_ENTRYPOINT_RE = re.compile(
    r"^(?P<module>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*):(?P<attribute>[A-Za-z_]\w*)$"
)
_COMPONENT_PREFIX = "DVTEXT"
_DEFAULT_ROUTER_LIFESPAN_TYPE = type(APIRouter().lifespan_context)


@dataclass(frozen=True)
class ExtensionGatewayApp:
    extension_name: str
    display_name: str
    app: FastAPI
    openapi_schema: dict[str, Any]


@dataclass
class ExtensionGatewayPrepareReport:
    loaded: dict[str, RegisteredExtension] = field(default_factory=dict)
    apps: dict[str, ExtensionGatewayApp] = field(default_factory=dict)
    failures: dict[str, ExtensionLoadFailure] = field(default_factory=dict)


def _failure(name: str, stage: str, exc: BaseException | str) -> ExtensionLoadFailure:
    return ExtensionLoadFailure(extension_name=name, stage=stage, message=str(exc))


def _validate_router(_extension: RegisteredExtension, router: APIRouter) -> None:
    if router.on_startup or router.on_shutdown:
        raise ValueError("Extension routers cannot register startup/shutdown handlers")
    if not isinstance(router.lifespan_context, _DEFAULT_ROUTER_LIFESPAN_TYPE):
        raise TypeError("Extension router cannot register a custom lifespan")

    seen: set[tuple[str, str]] = set()
    operation_ids: set[str] = set()
    for route in router.routes:
        if isinstance(route, APIRoute):
            route_methods = route.methods or set()
            for method in route_methods:
                key = (route.path, method.upper())
                if key in seen:
                    raise ValueError(
                        f"Duplicate extension route: {method.upper()} {route.path}"
                    )
                seen.add(key)
            if route.operation_id:
                if route.operation_id in operation_ids:
                    raise ValueError(f"Duplicate extension operation_id: {route.operation_id}")
                operation_ids.add(route.operation_id)
            continue

        if isinstance(route, APIWebSocketRoute):
            key = (route.path, "WEBSOCKET")
            if key in seen:
                raise ValueError(f"Duplicate extension WebSocket route: {route.path}")
            seen.add(key)
            continue

        raise TypeError(
            "Extension gateway_entrypoint may contain only FastAPI HTTP/WebSocket routes; "
            f"got {type(route).__name__}"
        )


def _load_router(extension: RegisteredExtension) -> APIRouter | None:
    entrypoint = extension.backend.gateway_entrypoint
    if not entrypoint:
        return None
    match = _ENTRYPOINT_RE.fullmatch(entrypoint.strip())
    if not match:
        raise ValueError("gateway_entrypoint must use 'module.path:attribute' format")

    prefix = ensure_extension_root_namespace(extension)
    module_name = f"{prefix}.{match.group('module')}"
    importlib.invalidate_caches()
    with _temporary_sys_path([extension.root_dir]):
        module = importlib.import_module(module_name)
    module_file = getattr(module, "__file__", None)
    if not module_file:
        raise ValueError("gateway_entrypoint module must resolve to a file inside extension root")
    try:
        Path(module_file).resolve().relative_to(extension.root_dir.resolve())
    except ValueError as exc:
        raise ValueError("gateway_entrypoint module escapes extension root") from exc
    value = getattr(module, match.group("attribute"), None)
    if not isinstance(value, APIRouter):
        raise TypeError(
            "gateway_entrypoint must resolve to fastapi.APIRouter, "
            f"got {type(value).__name__}"
        )
    _validate_router(extension, value)
    return value


def _build_child_app(extension: RegisteredExtension, router: APIRouter) -> ExtensionGatewayApp:
    display_name = extension.display_name or extension.name
    tag = f"Extension: {display_name}"
    child = FastAPI(
        title=display_name,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    child.include_router(router, tags=[tag])
    for route in child.routes:
        if not isinstance(route, APIRoute):
            continue
        route.openapi_extra = {
            **(route.openapi_extra or {}),
            "x-dvt-extension": extension.name,
        }
    return ExtensionGatewayApp(
        extension_name=extension.name,
        display_name=display_name,
        app=child,
        openapi_schema=child.openapi(),
    )


def prepare_extension_gateway_runtime(
    specs: list[ExtensionRuntimeSpec],
) -> ExtensionGatewayPrepareReport:
    report = ExtensionGatewayPrepareReport()
    for spec in sorted(specs, key=lambda item: item.name.casefold()):
        extension: RegisteredExtension | None = None
        try:
            extension = load_manifest(spec.root_dir.resolve(), extension_name=spec.name)
            if extension is None:
                raise ValueError(f"Manifest not found in '{spec.root_dir}'")
            if not check_dvt_compatibility(extension):
                raise ValueError(f"Extension '{spec.name}' is incompatible with current DVT")
            report.loaded[spec.name] = extension
            if not extension.backend.gateway_entrypoint:
                continue
            # The fresh generation is imported before the candidate is published.
            purge_extension_modules(extension)
            router = _load_router(extension)
            if router is not None:
                report.apps[spec.name] = _build_child_app(extension, router)
        except Exception as exc:
            stage = "gateway_import"
            if extension is None:
                stage = "manifest"
            elif isinstance(exc, (TypeError, ValueError)) and "route" in str(exc).lower():
                stage = "gateway_validation"
            report.failures[spec.name] = _failure(spec.name, stage, exc)
            report.loaded.pop(spec.name, None)
            report.apps.pop(spec.name, None)
            if extension is not None:
                purge_extension_modules(extension)
    return report


def _namespace_extension_components(
    schema: dict[str, Any], extension_name: str
) -> dict[str, Any]:
    schema = copy.deepcopy(schema)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", extension_name).strip("_") or "extension"
    digest = hashlib.sha256(extension_name.encode("utf-8")).hexdigest()[:8]
    prefix = f"{_COMPONENT_PREFIX}_{safe}_{digest}__"
    components = schema.get("components") or {}
    rename: dict[tuple[str, str], str] = {}
    for category, values in components.items():
        if not isinstance(values, dict):
            continue
        for name in values:
            rename[(category, name)] = f"{prefix}{name}"

    def rewrite(value: Any) -> Any:
        if isinstance(value, str) and value.startswith("#/components/"):
            parts = value.split("/", 3)
            if len(parts) == 4:
                new_name = rename.get((parts[2], parts[3]))
                if new_name:
                    return f"#/components/{parts[2]}/{new_name}"
            return value
        if isinstance(value, dict):
            result = {key: rewrite(item) for key, item in value.items()}
            security = result.get("security")
            if isinstance(security, list):
                result["security"] = [
                    {
                        rename.get(("securitySchemes", key), key): scopes
                        for key, scopes in requirement.items()
                    }
                    if isinstance(requirement, dict)
                    else requirement
                    for requirement in security
                ]
            return result
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        return value

    schema = rewrite(schema)
    rewritten_components = schema.get("components") or {}
    for category, values in list(rewritten_components.items()):
        if not isinstance(values, dict):
            continue
        rewritten_components[category] = {
            rename.get((category, name), name): value for name, value in values.items()
        }

    for path_item in (schema.get("paths") or {}).values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            if isinstance(operation_id, str) and operation_id:
                operation["operationId"] = f"{prefix}{operation_id}"
    return schema


async def _not_found(scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] == "websocket":
        await WebSocketClose(code=1008, reason="Extension route not found")(
            scope, receive, send
        )
        return
    await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)


class ExtensionGatewayRuntime:
    """Stable ASGI dispatcher backed by an atomically replaced child-app mapping."""

    def __init__(self) -> None:
        self._active: Mapping[str, ExtensionGatewayApp] = MappingProxyType({})
        self._generation = 0
        self._openapi_cache: tuple[int, int, dict[str, Any]] | None = None
        # Keep the mounted runtime compatible with tooling that applies FastAPI
        # dependency overrides to every mounted application. Child apps share
        # this mutable mapping, so overrides added after a swap are visible too.
        self.dependency_overrides: dict[Any, Any] = {}

    @property
    def generation(self) -> int:
        with RUNTIME_LOCK:
            return self._generation

    def swap(self, apps: Mapping[str, ExtensionGatewayApp]) -> None:
        with RUNTIME_LOCK:
            prepared_apps = dict(apps)
            for extension_app in prepared_apps.values():
                current_overrides = extension_app.app.dependency_overrides
                if not isinstance(current_overrides, ChainMap):
                    extension_app.app.dependency_overrides = ChainMap(
                        current_overrides,
                        self.dependency_overrides,
                    )
            self._active = MappingProxyType(prepared_apps)
            self._generation += 1
            self._openapi_cache = None

    def remove(self, extension_name: str) -> None:
        with RUNTIME_LOCK:
            if extension_name not in self._active:
                return
            next_apps = dict(self._active)
            next_apps.pop(extension_name, None)
            self._active = MappingProxyType(next_apps)
            self._generation += 1
            self._openapi_cache = None

    def active_names(self) -> set[str]:
        with RUNTIME_LOCK:
            return set(self._active)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)
            return

        route_path = get_route_path(scope)
        app_root_path = scope.get("app_root_path", "")
        mounted_suffix = scope.get("root_path", "")
        if app_root_path and mounted_suffix.startswith(app_root_path):
            mounted_suffix = mounted_suffix[len(app_root_path):]
        if mounted_suffix and route_path.startswith(mounted_suffix):
            route_path = route_path[len(mounted_suffix):] or "/"
        parts = [part for part in route_path.split("/") if part]
        if len(parts) < 2 or parts[1] != "api":
            await _not_found(scope, receive, send)
            return

        extension_name = parts[0]
        with RUNTIME_LOCK:
            extension_app = self._active.get(extension_name)
        if extension_app is None:
            await _not_found(scope, receive, send)
            return

        child_path = "/" + "/".join(parts[2:]) if len(parts) > 2 else "/"
        child_scope = dict(scope)
        child_scope["path"] = child_path
        child_scope["raw_path"] = child_path.encode("utf-8")
        child_scope["root_path"] = (
            f"{scope.get('root_path', '').rstrip('/')}/{extension_name}/api"
        )
        child_scope["dvt_extension_name"] = extension_name
        await extension_app.app(child_scope, receive, send)

    def merge_openapi(self, core_schema: dict[str, Any]) -> dict[str, Any]:
        with RUNTIME_LOCK:
            generation = self._generation
            apps = dict(self._active)
            core_identity = id(core_schema)
            if self._openapi_cache and self._openapi_cache[:2] == (
                generation,
                core_identity,
            ):
                return copy.deepcopy(self._openapi_cache[2])

        merged = copy.deepcopy(core_schema)
        merged.setdefault("paths", {})
        merged.setdefault("components", {})
        merged.setdefault("tags", [])
        known_tags = {item.get("name") for item in merged["tags"] if isinstance(item, dict)}

        for extension_name, extension_app in sorted(apps.items()):
            schema = _namespace_extension_components(
                extension_app.openapi_schema, extension_name
            )
            for path, path_item in schema.get("paths", {}).items():
                effective = f"/extensions/{extension_name}/api{path if path.startswith('/') else '/' + path}"
                merged["paths"][effective] = path_item
            for category, values in (schema.get("components") or {}).items():
                target = merged["components"].setdefault(category, {})
                if isinstance(values, dict):
                    target.update(values)
            for tag in schema.get("tags", []) or []:
                if isinstance(tag, dict) and tag.get("name") not in known_tags:
                    merged["tags"].append(tag)
                    known_tags.add(tag.get("name"))

        with RUNTIME_LOCK:
            if generation == self._generation:
                self._openapi_cache = (generation, core_identity, copy.deepcopy(merged))
        return merged


_RUNTIME = ExtensionGatewayRuntime()


def get_extension_gateway_runtime() -> ExtensionGatewayRuntime:
    return _RUNTIME


__all__ = [
    "ExtensionGatewayApp",
    "ExtensionGatewayPrepareReport",
    "ExtensionGatewayRuntime",
    "get_extension_gateway_runtime",
    "prepare_extension_gateway_runtime",
]
