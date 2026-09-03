from __future__ import annotations

import json
from enum import Enum
from typing import Any, get_origin

from pydantic import BaseModel, TypeAdapter

from src.modules.app_settings.domain.definitions import SettingDefinition
from src.modules.app_settings.domain.entities import SettingChange, SettingValue
from src.modules.app_settings.domain.registry import SettingsRegistry
from src.modules.app_settings.domain.services import infer_setup_type, strip_optional

from .db_models import AppSettingChangeRecord, AppSettingValueRecord
from .schemas import AppSettingDefinitionSchema


class SettingValueCodec:
    def dumps(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        elif isinstance(value, Enum):
            value = value.value
        return json.dumps(value, ensure_ascii=False, default=str)

    def loads(self, payload: str | None) -> Any:
        if payload is None:
            return None
        return json.loads(payload)


def value_row_to_domain(
    row: AppSettingValueRecord,
    *,
    definition: SettingDefinition,
    registry: type[SettingsRegistry],
    codec: SettingValueCodec,
    decrypt_value,
) -> SettingValue:
    raw_payload = decrypt_value(row.value, definition=definition)
    raw_value = codec.loads(raw_payload)
    return SettingValue(
        key=row.key,
        value=registry.validate_value(row.key, raw_value),
        version=row.version,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


def change_row_to_domain(
    row: AppSettingChangeRecord,
    *,
    definition: SettingDefinition,
    registry: type[SettingsRegistry],
    codec: SettingValueCodec,
    decrypt_value,
) -> SettingChange:
    old_payload = decrypt_value(row.old_value, definition=definition)
    new_payload = decrypt_value(row.new_value, definition=definition)
    return SettingChange(
        key=row.key,
        old_value=(
            None
            if old_payload is None
            else registry.validate_value(row.key, codec.loads(old_payload))
        ),
        new_value=(
            None
            if new_payload is None
            else registry.validate_value(row.key, codec.loads(new_payload))
        ),
        changed_at=row.changed_at,
        changed_by=row.changed_by,
        change_reason=row.change_reason,
    )


def setting_definition_to_schema(definition: SettingDefinition) -> AppSettingDefinitionSchema:
    annotation, nullable = strip_optional(definition.type_)
    return AppSettingDefinitionSchema(
        key=definition.key,
        namespace=definition.namespace,
        group=definition.group,
        name=definition.name,
        value_type=_annotation_value_schema(annotation),
        nullable=nullable,
        default=_to_plain_value(definition.default),
        ge=definition.ge,
        le=definition.le,
        min_length=definition.min_length,
        max_length=definition.max_length,
        description=definition.description,
        secret=definition.secret,
        runtime_editable=definition.runtime_editable,
        bootstrap=definition.bootstrap,
        required=definition.required,
        read_env=definition.read_env,
        env_var=definition.env_var,
        setup_label=definition.setup_label,
        setup_type=infer_setup_type(definition.key, definition),
    )


def _annotation_value_schema(annotation: Any) -> dict[str, Any]:
    try:
        return TypeAdapter(annotation).json_schema()
    except Exception:
        origin = get_origin(annotation)
        return {"title": _type_name(origin or annotation)}


def _type_name(annotation: Any) -> str:
    name = getattr(annotation, "__name__", None)
    if name:
        return name.lower()
    return str(annotation).replace("typing.", "")


def _to_plain_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _to_plain_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_plain_value(item) for item in value]
    return value
