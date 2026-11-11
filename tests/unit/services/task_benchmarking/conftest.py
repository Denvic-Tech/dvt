import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from services.task_benchmarking.nodes import register_benchmark_nodes

from src.node_dsl import _init_nodes
from src.node_dsl.registry import nodes as nodes_registry

SCHEMAS_DIR = Path(__file__).resolve().parents[4] / "services" / "task_benchmarking" / "schemas"

_JSON_TYPES: dict[str, Callable[[Any], bool]] = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
}


def _schema_errors(value: Any, schema: dict, root: dict, path: str) -> list[str]:
    """Minimal JSON Schema subset used by the benchmark schemas (jsonschema is not installed)."""
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return _schema_errors(value, target, root, path)

    errors: list[str] = []
    expected_types = schema.get("type")
    if expected_types is not None:
        expected = [expected_types] if isinstance(expected_types, str) else expected_types
        if not any(_JSON_TYPES[name](value) for name in expected):
            return [f"{path}: expected {expected}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: {value} <= exclusiveMinimum {schema['exclusiveMinimum']}")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        errors.append(f"{path}: shorter than minLength {schema['minLength']}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            errors.extend(_schema_errors(item, schema["items"], root, f"{path}[{index}]"))
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        errors.extend(
            f"{path}: missing required '{key}'"
            for key in schema.get("required", [])
            if key not in value
        )
        for key, item in value.items():
            if key in properties:
                errors.extend(_schema_errors(item, properties[key], root, f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property '{key}'")
    for sub_schema in schema.get("allOf", []):
        errors.extend(_schema_errors(value, sub_schema, root, path))
    if "if" in schema:
        branch = "then" if not _schema_errors(value, schema["if"], root, path) else "else"
        if branch in schema:
            errors.extend(_schema_errors(value, schema[branch], root, path))
    return errors


@pytest.fixture
def schema_errors() -> Callable[[Any, str, str | None], list[str]]:
    def _validate(value: Any, schema_file: str, definition: str | None = None) -> list[str]:
        root = json.loads((SCHEMAS_DIR / schema_file).read_text(encoding="utf-8"))
        schema = root["$defs"][definition] if definition else root
        return _schema_errors(value, schema, root, "$")

    return _validate


@pytest.fixture
def benchmark_registry():
    """Built-in registry plus benchmark nodes; yields names registered by this fixture.

    The registry snapshot is taken after the built-in bootstrap and restored afterwards, so
    benchmark nodes never leak into other test modules.
    """
    nodes_registry.get_all()
    snapshot = _init_nodes._snapshot_registries()
    try:
        yield register_benchmark_nodes()
    finally:
        _init_nodes._restore_registries(snapshot, restore_bootstrap_state=True)
