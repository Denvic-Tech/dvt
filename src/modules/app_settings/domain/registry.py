from __future__ import annotations

from dataclasses import fields, replace
from typing import Any, cast, get_type_hints

from .definitions import (
    _SETTING_METADATA_KEY,
    Setting,
    SettingDefinition,
    SettingGroup,
    SettingsModel,
    SettingsNamespace,
)
from .exceptions import SettingNotFoundError
from .services import coerce_setting_value
from .value_objects import (
    AppSettings,
    AppSettingsValue,
    RuntimeNamespace,
    TypedAppSettings,
)


class SettingsRegistry[SettingsT: AppSettingsValue]:
    settings_model: type[SettingsT] | None = None

    @classmethod
    def namespaces(cls) -> dict[str, SettingsNamespace]:
        declared_namespaces = {
            name: value
            for name, value in vars(cls).items()
            if isinstance(value, SettingsNamespace)
        }
        if declared_namespaces or cls.settings_model is None:
            return declared_namespaces
        return cls._model_namespaces(cls.settings_model)

    @classmethod
    def all_definitions(cls) -> list[SettingDefinition]:
        definitions: list[SettingDefinition] = []
        for namespace, namespace_def in cls.namespaces().items():
            for name, item in namespace_def.items.items():
                if isinstance(item, Setting):
                    definitions.append(cls._build_definition(namespace, None, name, item))
                elif isinstance(item, SettingGroup):
                    for setting_name, setting in item.settings.items():
                        definitions.append(
                            cls._build_definition(namespace, name, setting_name, setting)
                        )
        return definitions

    @classmethod
    def get_definition(cls, key: str) -> SettingDefinition:
        for definition in cls.all_definitions():
            if definition.key == key:
                return definition
        raise SettingNotFoundError(f"App setting key not found: {key}")

    @classmethod
    def contains(cls, key: str) -> bool:
        return any(definition.key == key for definition in cls.all_definitions())

    @classmethod
    def default_values(cls) -> dict[str, Any]:
        return {
            definition.key: definition.default
            for definition in cls.all_definitions()
        }

    @classmethod
    def validate_value(cls, key: str, value: Any) -> Any:
        return coerce_setting_value(cls.get_definition(key), value)

    @classmethod
    def validate_values(cls, values: dict[str, Any]) -> dict[str, Any]:
        return {
            definition.key: coerce_setting_value(
                definition,
                values.get(definition.key, definition.default),
            )
            for definition in cls.all_definitions()
        }

    @classmethod
    def build_runtime_model(cls, values: dict[str, Any]) -> SettingsT:
        grouped: dict[str, dict[str, Any]] = {}
        for definition in cls.all_definitions():
            value = values.get(definition.key, definition.default)
            namespace_values = grouped.setdefault(definition.namespace, {})
            if definition.group is None:
                namespace_values[definition.name] = value
            else:
                group_values = namespace_values.setdefault(definition.group, {})
                group_values[definition.name] = value

        if cls.settings_model is not None:
            model_type = cast(type[TypedAppSettings], cls.settings_model)
            return cast(SettingsT, model_type.from_dict(grouped))

        return cast(
            SettingsT,
            AppSettings(
                namespaces={
                    namespace: RuntimeNamespace.from_dict(namespace_values)
                    for namespace, namespace_values in grouped.items()
                }
            ),
        )

    @classmethod
    def to_plain_value(cls, value: Any) -> Any:
        return value

    @staticmethod
    def _build_definition(
        namespace: str,
        group: str | None,
        name: str,
        setting: Setting,
    ) -> SettingDefinition:
        return SettingDefinition(
            namespace=namespace,
            group=group,
            name=name,
            type_=setting.type_,
            default=setting.get_default(),
            ge=setting.ge,
            le=setting.le,
            min_length=setting.min_length,
            max_length=setting.max_length,
            description=setting.description,
            secret=setting.secret,
            runtime_editable=setting.runtime_editable,
            bootstrap=setting.bootstrap,
            required=setting.required,
            read_env=setting.read_env,
            env_var=setting.env_var,
            setup_label=setting.setup_label,
            setup_type=setting.setup_type,
        )

    @classmethod
    def _model_namespaces(
        cls,
        model_type: type[SettingsT],
    ) -> dict[str, SettingsNamespace]:
        type_hints = get_type_hints(model_type)
        namespaces: dict[str, SettingsNamespace] = {}
        for model_field in fields(model_type):
            namespace_type = type_hints[model_field.name]
            if not cls._is_settings_model(namespace_type):
                raise TypeError(
                    f"App settings namespace must inherit SettingsModel: {model_field.name}"
                )
            namespaces[model_field.name] = cls._build_namespace(namespace_type)
        return namespaces

    @classmethod
    def _build_namespace(cls, namespace_type: type[SettingsModel]) -> SettingsNamespace:
        type_hints = get_type_hints(namespace_type)
        items: dict[str, Setting | SettingGroup] = {}
        for model_field in fields(namespace_type):
            field_type = type_hints[model_field.name]
            definition = model_field.metadata.get(_SETTING_METADATA_KEY)
            if isinstance(definition, Setting):
                items[model_field.name] = replace(definition, type_=field_type)
                continue
            if cls._is_settings_model(field_type):
                items[model_field.name] = cls._build_group(field_type)
                continue
            raise TypeError(
                f"App setting field must use setting(): "
                f"{namespace_type.__name__}.{model_field.name}"
            )
        return SettingsNamespace(**items)

    @classmethod
    def _build_group(cls, group_type: type[SettingsModel]) -> SettingGroup:
        type_hints = get_type_hints(group_type)
        settings: dict[str, Setting] = {}
        for model_field in fields(group_type):
            definition = model_field.metadata.get(_SETTING_METADATA_KEY)
            if not isinstance(definition, Setting):
                raise TypeError(
                    f"Nested app setting groups are not supported: "
                    f"{group_type.__name__}.{model_field.name}"
                )
            settings[model_field.name] = replace(
                definition,
                type_=type_hints[model_field.name],
            )
        return SettingGroup(**settings)

    @staticmethod
    def _is_settings_model(value: Any) -> bool:
        return isinstance(value, type) and issubclass(value, SettingsModel)
