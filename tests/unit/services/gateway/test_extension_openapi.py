import copy

from fastapi import FastAPI

from services.gateway.main import _core_openapi_schema, app
from src.extensions.gateway_runtime import (
    ExtensionGatewayApp,
    get_extension_gateway_runtime,
)


def test_runtime_openapi_changes_without_mutating_core_openapi() -> None:
    runtime = get_extension_gateway_runtime()
    runtime.swap({})
    core_before = copy.deepcopy(_core_openapi_schema)

    child = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @child.get("/ping", openapi_extra={"x-dvt-extension": "sample-extension"})
    async def ping():
        return {"ok": True}

    runtime.swap(
        {
            "sample-extension": ExtensionGatewayApp(
                extension_name="sample-extension",
                display_name="Sample Extension",
                app=child,
                openapi_schema=child.openapi(),
            )
        }
    )
    try:
        runtime_schema = app.openapi()
        assert "/extensions/sample-extension/api/ping" in runtime_schema["paths"]
        assert _core_openapi_schema == core_before
        assert "/extensions/sample-extension/api/ping" not in _core_openapi_schema["paths"]
    finally:
        runtime.swap({})
