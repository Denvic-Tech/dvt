"""Every local $ref in the core OpenAPI document must point at an existing component."""

from __future__ import annotations

import re
from typing import Any

from services.gateway.main import _core_openapi_schema

_LOCAL_REF = re.compile(r"^#/components/([a-zA-Z]+)/([^/]+)$")


def _iter_refs(node: Any, path: str = "$"):
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            yield path, ref
        for key, value in node.items():
            yield from _iter_refs(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _iter_refs(value, f"{path}[{index}]")


def test_core_openapi_refs_resolve() -> None:
    components = _core_openapi_schema.get("components", {})
    broken: list[tuple[str, str]] = []
    for path, ref in _iter_refs(_core_openapi_schema):
        if not ref.startswith("#/"):
            continue
        match = _LOCAL_REF.match(ref)
        if match is None or match.group(2) not in components.get(match.group(1), {}):
            broken.append((path, ref))
    assert broken == []


def test_import_payload_schema_is_registered() -> None:
    schemas = _core_openapi_schema["components"]["schemas"]
    for name in (
        "ImportRequestSchema",
        "ConflictDecision",
        "ConnectionDecisionAction",
        "ConnectionDecisionSchema",
        "ImportMode",
        "MergeStrategy",
        "VariableDecisionSchema",
        "ScheduleDecisionSchema",
    ):
        assert name in schemas, name
    for route in ("/projects/import", "/projects/import/preview"):
        extension = _core_openapi_schema["paths"][route]["post"]["x-dvt-payload-schema"]
        assert extension == {"$ref": "#/components/schemas/ImportRequestSchema"}
