"""Refresh only the SDK dataframe metadata models from a Gateway OpenAPI snapshot.

The checkout has no full Python SDK generator. This bounded synchronizer leaves
endpoint resources and unrelated models untouched. Fetch the snapshot first with
scripts/misc/generate_gateway_openapi_hash.py.
"""

import argparse
import json
import keyword
import re
from pathlib import Path

MODEL_NAMES = ("ArrowFieldMetadata", "ArrowTypeMetadata", "DTypeMetadata")


def annotation(schema: dict) -> str:
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        if name not in MODEL_NAMES:
            raise ValueError(f"Unexpected metadata reference: {name}")
        return name
    if "anyOf" in schema:
        return " | ".join(annotation(item) for item in schema["anyOf"])
    if "enum" in schema:
        return "Literal[" + ", ".join(repr(item) for item in schema["enum"]) + "]"
    if schema.get("type") == "array":
        return f"list[{annotation(schema['items'])}]"
    types = {"string": "str", "integer": "int", "boolean": "bool", "null": "None"}
    return types[schema["type"]]


def render_model(name: str, schema: dict) -> str:
    lines = [
        f"class {name}(SDKBaseModel):",
        "    model_config = ConfigDict(populate_by_name=True, extra='allow')",
    ]
    required = schema.get("required", [])
    for field, definition in schema["properties"].items():
        identifier = field + "_" if keyword.iskeyword(field) else field
        if not identifier.isidentifier():
            raise ValueError(f"Unsupported metadata field: {field}")
        default = "..." if field in required else repr(definition.get("default"))
        arguments = [default]
        if identifier != field:
            arguments.append(f"alias={field!r}")
        if "description" in definition:
            arguments.append(f"description={definition['description']!r}")
        lines.append(f"    {identifier}: {annotation(definition)} = Field({', '.join(arguments)})")
    return "\n".join(lines) + "\n"


def synchronize(snapshot: Path, models: Path) -> None:
    schemas = json.loads(snapshot.read_text(encoding="utf-8"))["components"]["schemas"]
    raw = models.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    source = raw.decode("utf-8").replace("\r\n", "\n")
    enum = (
        "DataType: TypeAlias = Literal["
        + ", ".join(repr(item) for item in schemas["DataType"]["enum"])
        + "]"
    )
    source, count = re.subn(r"^DataType: TypeAlias = .*$", lambda _: enum, source, flags=re.M)
    if count != 1:
        raise ValueError("Expected exactly one SDK DataType alias")
    for name in MODEL_NAMES:
        rendered = render_model(name, schemas[name])
        pattern = rf"^class {name}\(SDKBaseModel\):\n(?:[ \t]+[^\n]*\n|\n)*"
        source, count = re.subn(
            pattern, lambda _, rendered=rendered: rendered + "\n", source, flags=re.M
        )
        if count == 0:
            source = source.replace(
                "class DTypeMetadata(SDKBaseModel):",
                rendered + "\nclass DTypeMetadata(SDKBaseModel):",
                1,
            )
        if count > 1:
            raise ValueError(f"Duplicate SDK model: {name}")
        if f"{name}.model_rebuild()" not in source:
            source = source.replace(
                "DTypeMetadata.model_rebuild()",
                f"{name}.model_rebuild()\nDTypeMetadata.model_rebuild()",
                1,
            )
        if f"    '{name}'," not in source:
            source = source.replace("__all__ = [", f"__all__ = [\n    '{name}',", 1)
    compile(source, str(models), "exec")
    models.write_bytes(source.replace("\n", newline).encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument(
        "--models", type=Path, default=Path("src/clients/gateway_sdk/generated/models.py")
    )
    args = parser.parse_args()
    synchronize(args.snapshot, args.models)


if __name__ == "__main__":
    main()
