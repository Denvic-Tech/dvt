from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model
from pydantic.fields import FieldInfo

from src.modules.app_settings.domain.definitions import Setting, SettingGroup, SettingsNamespace
from src.modules.app_settings.domain.registry import SettingsRegistry


def _optional(annotation: Any) -> Any:
    try:
        return annotation | None
    except TypeError:
        return Any | None


def _model_name(*parts: str) -> str:
    return "".join(part.capitalize() for part in parts if part)


def _setting_field(setting: Setting, *, update: bool) -> tuple[Any, FieldInfo]:
    annotation = _optional(setting.type_) if update else setting.type_
    return annotation, Field(
        default=None,
        description=setting.description,
    )


def _build_namespace_model(
    *,
    namespace_name: str,
    namespace: SettingsNamespace,
    suffix: str,
    update: bool,
) -> type[BaseModel]:
    fields: dict[str, tuple[Any, FieldInfo]] = {}
    for item_name, item in namespace.items.items():
        if isinstance(item, Setting):
            fields[item_name] = _setting_field(item, update=update)
            continue
        if isinstance(item, SettingGroup):
            group_model = _build_group_model(
                namespace_name=namespace_name,
                group_name=item_name,
                group=item,
                suffix=suffix,
                update=update,
            )
            fields[item_name] = (
                _optional(group_model) if update else group_model,
                Field(default=None),
            )

    return create_model(
        f"AppSettings{_model_name(namespace_name)}{suffix}Schema",
        __base__=BaseModel,
        __config__=ConfigDict(populate_by_name=True),
        **fields,
    )


def _build_group_model(
    *,
    namespace_name: str,
    group_name: str,
    group: SettingGroup,
    suffix: str,
    update: bool,
) -> type[BaseModel]:
    return create_model(
        f"AppSettings{_model_name(namespace_name, group_name)}{suffix}Schema",
        __base__=BaseModel,
        __config__=ConfigDict(populate_by_name=True),
        **{
            setting_name: _setting_field(setting, update=update)
            for setting_name, setting in group.settings.items()
        },
    )


def build_app_settings_schema(
    registry: type[SettingsRegistry],
    *,
    name: str,
    update: bool,
) -> type[BaseModel]:
    suffix = "Update" if update else "Read"
    fields: dict[str, tuple[Any, FieldInfo]] = {}
    for namespace_name, namespace in registry.namespaces().items():
        namespace_model = _build_namespace_model(
            namespace_name=namespace_name,
            namespace=namespace,
            suffix=suffix,
            update=update,
        )
        fields[namespace_name] = (
            _optional(namespace_model) if update else namespace_model,
            Field(default=None),
        )

    return create_model(
        name,
        __base__=BaseModel,
        __config__=ConfigDict(populate_by_name=True),
        **fields,
    )
