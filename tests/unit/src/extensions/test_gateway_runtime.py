from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.extensions.gateway_runtime import (
    ExtensionGatewayRuntime,
    _namespace_extension_components,
    prepare_extension_gateway_runtime,
)
from src.extensions.runtime import ExtensionRuntimeSpec
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
