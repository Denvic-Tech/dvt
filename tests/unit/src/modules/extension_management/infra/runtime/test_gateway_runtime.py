from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.modules.extension_management.infra.runtime import loader, registry
from src.modules.extension_management.infra.runtime.gateway_runtime import (
    ExtensionGatewayRuntime,
    _namespace_extension_components,
    prepare_extension_gateway_runtime,
)
from src.modules.extension_management.infra.runtime.runtime import ExtensionRuntimeSpec
from src.modules.user.infra.fastapi.dependencies import (
    get_user_access_only,
    get_user_admin_access_only,
)


def _write_gateway_extension(root: Path, response: str = "pong") -> None:
    backend = root / "backend"
    backend.mkdir(parents=True, exist_ok=True)
    (backend / "__init__.py").write_text("", encoding="utf-8")
    (backend / "gateway.py").write_text(
        f"""
from fastapi import APIRouter

router = APIRouter()

@router.get("/ping")
async def ping():
    return {{"message": {response!r}}}
""",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        """
[project]
name = "sample-extension"
version = "1.0.0"

[tool.dvt_extension]
name = "sample-extension"
display_name = "Sample Extension"

[tool.dvt_extension.backend]
gateway_entrypoint = "backend.gateway:router"
""",
        encoding="utf-8",
    )


def _client(runtime: ExtensionGatewayRuntime, *, root_path: str = "") -> TestClient:
    app = FastAPI(root_path=root_path)
    app.mount("/extensions", runtime)
    return TestClient(app)


def _write_gateway_extension_with_absolute_backend_import(
    root: Path, *, backend_name: str, response: str
) -> None:
    backend = root / backend_name
    backend.mkdir(parents=True, exist_ok=True)
    (backend / "__init__.py").write_text("", encoding="utf-8")
    (backend / "helper.py").write_text(f"RESPONSE = {response!r}\n", encoding="utf-8")
    (backend / "gateway.py").write_text(
        f"""
from fastapi import APIRouter
from {backend_name}.helper import RESPONSE

router = APIRouter()

@router.get("/ping")
async def ping():
    return {{"message": RESPONSE}}
""",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        f"""
[project]
name = "sample-extension"
version = "1.0.0"

[tool.dvt_extension]
name = "sample-extension"
display_name = "Sample Extension"

[tool.dvt_extension.backend]
gateway_entrypoint = "{backend_name}.gateway:router"
""",
        encoding="utf-8",
    )


def test_gateway_runtime_hot_add_remove_reload_and_openapi(tmp_path: Path) -> None:
    extension_root = tmp_path / "sample-extension"
    extension_root.mkdir()
    _write_gateway_extension(extension_root)
    runtime = ExtensionGatewayRuntime()
    client = _client(runtime)
    assert client.get("/extensions/sample-extension/api/ping").status_code == 404

    report = prepare_extension_gateway_runtime(
        [ExtensionRuntimeSpec("sample-extension", extension_root)]
    )
    assert not report.failures
    runtime.swap(report.apps)
    response = client.get("/extensions/sample-extension/api/ping")
    assert response.status_code == 200
    assert response.json() == {"message": "pong"}

    schema = runtime.merge_openapi({"openapi": "3.1.0", "paths": {}})
    operation = schema["paths"]["/extensions/sample-extension/api/ping"]["get"]
    assert operation["x-dvt-extension"] == "sample-extension"
    assert "Extension: Sample Extension" in operation["tags"]

    _write_gateway_extension(extension_root, response="new-pong-value")
    report = prepare_extension_gateway_runtime(
        [ExtensionRuntimeSpec("sample-extension", extension_root)]
    )
    assert not report.failures
    runtime.swap(report.apps)
    assert client.get("/extensions/sample-extension/api/ping").json() == {
        "message": "new-pong-value"
    }

    runtime.remove("sample-extension")
    assert client.get("/extensions/sample-extension/api/ping").status_code == 404


def test_gateway_runtime_root_transition_drops_stale_absolute_backend_import(
    tmp_path: Path,
) -> None:
    backend_name = "dvt_test_gateway_backend_transition"
    old_root = tmp_path / "old-extension-root"
    new_root = tmp_path / "new-extension-root"
    _write_gateway_extension_with_absolute_backend_import(
        old_root, backend_name=backend_name, response="old"
    )
    _write_gateway_extension_with_absolute_backend_import(
        new_root, backend_name=backend_name, response="new"
    )

    old_report = prepare_extension_gateway_runtime(
        [ExtensionRuntimeSpec("sample-extension", old_root)]
    )
    assert old_report.failures == {}
    registry.add(old_report.loaded["sample-extension"])

    new_report = prepare_extension_gateway_runtime(
        [ExtensionRuntimeSpec("sample-extension", new_root)]
    )

    assert new_report.failures == {}
    runtime = ExtensionGatewayRuntime()
    runtime.swap(new_report.apps)
    assert _client(runtime).get("/extensions/sample-extension/api/ping").json() == {
        "message": "new"
    }

    loader.purge_extension_modules(new_report.loaded["sample-extension"])
    registry.clear()


def test_gateway_runtime_shares_dependency_overrides_with_child_apps(tmp_path: Path) -> None:
    extension_root = tmp_path / "sample-extension"
    extension_root.mkdir()
    _write_gateway_extension(extension_root)
    report = prepare_extension_gateway_runtime(
        [ExtensionRuntimeSpec("sample-extension", extension_root)]
    )
    runtime = ExtensionGatewayRuntime()

    runtime.swap(report.apps)

    def override():
        return object()

    runtime.dependency_overrides[object] = override

    child = report.apps["sample-extension"].app
    assert child.dependency_overrides[object] is override


def test_gateway_runtime_works_with_gateway_root_path(tmp_path: Path) -> None:
    extension_root = tmp_path / "sample-extension"
    extension_root.mkdir()
    _write_gateway_extension(extension_root)
    runtime = ExtensionGatewayRuntime()
    report = prepare_extension_gateway_runtime(
        [ExtensionRuntimeSpec("sample-extension", extension_root)]
    )
    runtime.swap(report.apps)

    response = _client(runtime, root_path="/api").get(
        "/extensions/sample-extension/api/ping"
    )

    assert response.status_code == 200
    assert response.json() == {"message": "pong"}


def test_gateway_runtime_supports_websocket_routes(tmp_path: Path) -> None:
    extension_root = tmp_path / "websocket-extension"
    backend = extension_root / "backend"
    backend.mkdir(parents=True)
    (backend / "__init__.py").write_text("", encoding="utf-8")
    (backend / "gateway.py").write_text(
        """
from fastapi import APIRouter, WebSocket

router = APIRouter()

@router.websocket("/events")
async def events(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json({"message": "connected"})
    await websocket.close()
""",
        encoding="utf-8",
    )
    (extension_root / "pyproject.toml").write_text(
        """
[project]
name = "websocket-extension"
version = "1.0.0"
[tool.dvt_extension]
name = "websocket-extension"
[tool.dvt_extension.backend]
gateway_entrypoint = "backend.gateway:router"
""",
        encoding="utf-8",
    )

    report = prepare_extension_gateway_runtime(
        [ExtensionRuntimeSpec("websocket-extension", extension_root)]
    )

    assert not report.failures
    runtime = ExtensionGatewayRuntime()
    runtime.swap(report.apps)
    client = _client(runtime)
    with client.websocket_connect(
        "/extensions/websocket-extension/api/events"
    ) as websocket:
        assert websocket.receive_json() == {"message": "connected"}

    runtime.remove("websocket-extension")
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(
        "/extensions/websocket-extension/api/events"
    ):
        pass
    assert exc_info.value.code == 1008


def test_gateway_runtime_rejects_custom_router_lifespan(tmp_path: Path) -> None:
    extension_root = tmp_path / "lifespan-extension"
    backend = extension_root / "backend"
    backend.mkdir(parents=True)
    (backend / "__init__.py").write_text("", encoding="utf-8")
    (backend / "gateway.py").write_text(
        """
from contextlib import asynccontextmanager
from fastapi import APIRouter

@asynccontextmanager
async def lifespan(_app):
    yield

router = APIRouter(lifespan=lifespan)
""",
        encoding="utf-8",
    )
    (extension_root / "pyproject.toml").write_text(
        """
[project]
name = "lifespan-extension"
version = "1.0.0"
[tool.dvt_extension]
name = "lifespan-extension"
[tool.dvt_extension.backend]
gateway_entrypoint = "backend.gateway:router"
""",
        encoding="utf-8",
    )

    report = prepare_extension_gateway_runtime(
        [ExtensionRuntimeSpec("lifespan-extension", extension_root)]
    )

    assert report.apps == {}
    failure = report.failures["lifespan-extension"]
    assert failure.stage == "gateway_validation"
    assert "lifespan" in failure.message.lower()


def test_gateway_openapi_namespaces_discriminator_mapping_refs() -> None:
    schema = {
        "paths": {
            "/pets": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "oneOf": [
                                        {"$ref": "#/components/schemas/Cat"},
                                        {"$ref": "#/components/schemas/Dog"},
                                    ],
                                    "discriminator": {
                                        "propertyName": "kind",
                                        "mapping": {
                                            "cat": "#/components/schemas/Cat",
                                            "dog": "#/components/schemas/Dog",
                                        },
                                    },
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "Cat": {"type": "object"},
                "Dog": {"type": "object"},
            }
        },
    }

    namespaced = _namespace_extension_components(schema, "sample-extension")
    request_schema = namespaced["paths"]["/pets"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]

    assert request_schema["oneOf"] == [
        {"$ref": "#/components/schemas/DVTEXT_sample_extension_3ca52256__Cat"},
        {"$ref": "#/components/schemas/DVTEXT_sample_extension_3ca52256__Dog"},
    ]
    assert request_schema["discriminator"]["mapping"] == {
        "cat": "#/components/schemas/DVTEXT_sample_extension_3ca52256__Cat",
        "dog": "#/components/schemas/DVTEXT_sample_extension_3ca52256__Dog",
    }


def test_gateway_openapi_namespace_avoids_normalized_name_and_operation_id_collisions() -> None:
    schema = {
        "paths": {
            "/ping": {
                "get": {
                    "operationId": "ping_ping_get",
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
        "components": {"schemas": {"Payload": {"type": "object"}}},
    }

    hyphenated = _namespace_extension_components(schema, "foo-bar")
    underscored = _namespace_extension_components(schema, "foo_bar")

    assert set(hyphenated["components"]["schemas"]) == {
        "DVTEXT_foo_bar_7d89c4f5__Payload"
    }
    assert set(underscored["components"]["schemas"]) == {
        "DVTEXT_foo_bar_4928cae8__Payload"
    }
    assert (
        hyphenated["paths"]["/ping"]["get"]["operationId"]
        != underscored["paths"]["/ping"]["get"]["operationId"]
    )


def test_gateway_runtime_rejects_non_router_entrypoint(tmp_path: Path) -> None:
    extension_root = tmp_path / "sample-extension"
    backend = extension_root / "backend"
    backend.mkdir(parents=True)
    (backend / "__init__.py").write_text("", encoding="utf-8")
    (backend / "gateway.py").write_text("router = object()\n", encoding="utf-8")
    (extension_root / "pyproject.toml").write_text(
        """
[project]
name = "sample-extension"
version = "1.0.0"
[tool.dvt_extension]
name = "sample-extension"
[tool.dvt_extension.backend]
gateway_entrypoint = "backend.gateway:router"
""",
        encoding="utf-8",
    )
    report = prepare_extension_gateway_runtime(
        [ExtensionRuntimeSpec("sample-extension", extension_root)]
    )

    assert report.apps == {}
    assert report.failures["sample-extension"].stage == "gateway_validation"


def test_gateway_extension_auth_is_route_level_and_uses_public_dependencies(
    tmp_path: Path,
) -> None:
    extension_root = tmp_path / "auth-extension"
    backend = extension_root / "backend"
    backend.mkdir(parents=True)
    (backend / "__init__.py").write_text("", encoding="utf-8")
    (backend / "gateway.py").write_text(
        """
from fastapi import APIRouter
from dvt_extension_api.v1.gateway import CurrentAdminDep, CurrentUserDep

router = APIRouter()

@router.get("/public")
async def public_route():
    return {"access": "public"}

@router.get("/user")
async def user_route(user: CurrentUserDep):
    return {"user_id": str(user.id)}

@router.get("/admin")
async def admin_route(user: CurrentAdminDep):
    return {"user_id": str(user.id)}
""",
        encoding="utf-8",
    )
    (extension_root / "pyproject.toml").write_text(
        """
[project]
name = "auth-extension"
version = "1.0.0"
[tool.dvt_extension]
name = "auth-extension"
[tool.dvt_extension.backend]
gateway_entrypoint = "backend.gateway:router"
""",
        encoding="utf-8",
    )

    report = prepare_extension_gateway_runtime(
        [ExtensionRuntimeSpec("auth-extension", extension_root)]
    )
    assert not report.failures
    extension_app = report.apps["auth-extension"].app
    extension_app.dependency_overrides[get_user_access_only] = lambda: SimpleNamespace(id="user-1")
    extension_app.dependency_overrides[get_user_admin_access_only] = lambda: SimpleNamespace(id="admin-1")
    runtime = ExtensionGatewayRuntime()
    runtime.swap(report.apps)
    client = _client(runtime)

    assert client.get("/extensions/auth-extension/api/public").json() == {
        "access": "public"
    }
    assert client.get("/extensions/auth-extension/api/user").json() == {
        "user_id": "user-1"
    }
    assert client.get("/extensions/auth-extension/api/admin").json() == {
        "user_id": "admin-1"
    }


def test_canonical_route_and_legacy_alias_share_runtime_without_duplicate_openapi(tmp_path):
    root = tmp_path / "Old Display Name"
    _write_gateway_extension(root)
    report = prepare_extension_gateway_runtime([
        ExtensionRuntimeSpec("sample-extension", root, legacy_names=("Old Display Name",)),
    ])
    assert not report.failures
    runtime = ExtensionGatewayRuntime()
    runtime.swap(report.apps)
    client = _client(runtime)
    assert client.get("/extensions/sample-extension/api/ping").json() == {"message": "pong"}
    assert client.get("/extensions/Old%20Display%20Name/api/ping").json() == {"message": "pong"}
    paths = runtime.merge_openapi({"paths": {}})["paths"]
    assert set(paths) == {"/extensions/sample-extension/api/ping"}
    runtime.remove("sample-extension")
    assert client.get("/extensions/Old%20Display%20Name/api/ping").status_code == 404
