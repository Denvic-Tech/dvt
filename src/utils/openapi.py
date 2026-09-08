from collections.abc import Iterable, Mapping
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, TypeAdapter
from starlette.routing import Mount
from starlette.types import ASGIApp

REF_DEFS_PREFIX = "#/$defs/"
REF_COMP_PREFIX = "#/components/schemas/"


def _remap_refs(obj: Any) -> Any:
    """Глубокий проход по словарю/спискам и замена $ref из $defs в components.schemas."""
    if isinstance(obj, Mapping):
        obj = dict(obj)  # copy
        if "$ref" in obj and isinstance(obj["$ref"], str) and obj["$ref"].startswith(REF_DEFS_PREFIX):
            obj["$ref"] = REF_COMP_PREFIX + obj["$ref"][len(REF_DEFS_PREFIX):]
        for k, v in obj.items():
            obj[k] = _remap_refs(v)
        return obj
    if isinstance(obj, list):
        return [_remap_refs(x) for x in obj]
    return obj


def _add_schema_to_components(openapi: dict, name: str, schema: dict):
    comps = openapi.setdefault("components", {}).setdefault("schemas", {})
    # Вынесем $defs в components.schemas
    defs = schema.pop("$defs", {})
    schema = _remap_refs(schema)  # перепишем $ref внутри основной схемы
    comps[name] = schema
    for def_name, def_schema in defs.items():
        comps.setdefault(def_name, _remap_refs(def_schema))


def rebuild_openapi(
        app: FastAPI,
        include_models: Iterable[type[BaseModel] | tuple[str, type]] | None = None,
):
    base_openapi = app.openapi()

    # --- мердж OpenAPI смонтированных приложений (как было у тебя) ---
    for route in app.routes:
        if isinstance(route, Mount):
            sub_app: ASGIApp = route.app
            prefix = route.path
            if hasattr(sub_app, "openapi") and callable(sub_app.openapi):
                sub_app_openapi = sub_app.openapi()
                if hasattr(sub_app, "root_path") and isinstance(sub_app.root_path, str):
                    prefix += sub_app.root_path

                for path, item in sub_app_openapi.get("paths", {}).items():
                    base_openapi.setdefault("paths", {})[f"{prefix}{path}"] = item

                for comp_key in ("schemas", "parameters", "responses", "requestBodies", "headers", "securitySchemes"):
                    base_openapi.setdefault("components", {}).setdefault(comp_key, {})
                    for name, val in sub_app_openapi.get("components", {}).get(comp_key, {}).items():
                        base_openapi["components"][comp_key].setdefault(name, val)

    # --- добавляем явно указанные модели ---
    include_models = include_models or []
    for model in include_models:

        if issubclass(model, BaseModel):
            name = model.__name__
            schema = model.model_json_schema(ref_template="#/components/schemas/{model}")

        elif isinstance(model, tuple):
            name, _type = model
            ta = TypeAdapter(_type)
            schema = ta.json_schema(ref_template="#/components/schemas/{model}")

        else:
            raise TypeError(f"Bad model: {model}")

        # ВАЖНО: просим pydantic генерировать ссылки сразу в components.schemas
        _add_schema_to_components(base_openapi, name, schema)

    # --- финальный проход: переписать любые оставшиеся $ref из $defs ---
    base_openapi = _remap_refs(base_openapi)

    # Если хочешь — положи схему обратно в приложение:
    app.openapi_schema = base_openapi
    return app
