from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .type_system import infer_variable_scalar_type_from_annotation

from src.node_dsl.node_typing import IO


def resolve_system_variable_io_type(annotation: Any) -> IO:
    resolved_type = infer_variable_scalar_type_from_annotation(annotation)
    if resolved_type is not None:
        return resolved_type
    raise ValueError(f"Unsupported system variable annotation '{annotation}'.")


def build_system_variable_type_map(model_cls: type[BaseModel] | None) -> dict[str, IO]:
    if model_cls is None:
        return {}

    if not issubclass(model_cls, BaseModel):
        raise TypeError("SYSTEM_VARIABLES_MODEL must be a subclass of pydantic.BaseModel.")

    return {
        field_name: resolve_system_variable_io_type(field_info.annotation)
        for field_name, field_info in model_cls.model_fields.items()
    }


def build_system_variable_definition_payloads(model_cls: type[BaseModel] | None) -> dict[str, dict[str, Any]]:
    if model_cls is None:
        return {}

    system_variable_types = build_system_variable_type_map(model_cls)

    payloads: dict[str, dict[str, Any]] = {}
    for field_name, field_info in model_cls.model_fields.items():
        payloads[field_name] = {
            "type": system_variable_types[field_name],
            "required": field_info.is_required(),
            "display_name": field_info.title,
            "description": field_info.description,
        }

    return payloads
