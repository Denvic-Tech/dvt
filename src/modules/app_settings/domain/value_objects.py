from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Protocol, Self, cast, get_type_hints

from .definitions import SettingsModel


@dataclass(frozen=True)
class RuntimeNamespace:
    values: dict[str, Any]

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> Self:
        return cls(
            values={
                key: cls.from_dict(value) if isinstance(value, dict) else value
                for key, value in values.items()
            }
        )

    def __getattr__(self, item: str) -> Any:
        try:
            return self.values[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def as_dict(self) -> dict[str, Any]:
        return {
            key: value.as_dict() if isinstance(value, RuntimeNamespace) else value
            for key, value in self.values.items()
        }


@dataclass(frozen=True)
class AppSettings:
    namespaces: dict[str, RuntimeNamespace]

    def __getattr__(self, item: str) -> RuntimeNamespace:
        try:
            return self.namespaces[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def get(self, key: str) -> Any:
        parts = key.split(".")
        if len(parts) not in {2, 3}:
            raise KeyError(key)
        value: Any = self.namespaces[parts[0]]
        for part in parts[1:]:
            value = value.values[part] if isinstance(value, RuntimeNamespace) else value[part]
        return value

    def keys(self) -> list[str]:
        result: list[str] = []
        for namespace, values in self.namespaces.items():
            for name, value in values.values.items():
                if isinstance(value, RuntimeNamespace):
                    result.extend(f"{namespace}.{name}.{setting}" for setting in value.values)
                else:
                    result.append(f"{namespace}.{name}")
        return result

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {
            namespace: values.as_dict()
            for namespace, values in self.namespaces.items()
        }


class TypedAppSettings(SettingsModel):
    def get(self, key: str) -> Any:
        parts = key.split(".")
        if len(parts) not in {2, 3}:
            raise KeyError(key)
        value: Any = self
        try:
            for part in parts:
                value = getattr(value, part)
        except AttributeError as exc:
            raise KeyError(key) from exc
        return value

    def keys(self) -> list[str]:
        result: list[str] = []

        def collect(value: SettingsModel, parts: tuple[str, ...]) -> None:
            for model_field in fields(value):
                field_value = getattr(value, model_field.name)
                field_parts = (*parts, model_field.name)
                if isinstance(field_value, SettingsModel):
                    collect(field_value, field_parts)
                else:
                    result.append(".".join(field_parts))

        collect(self, ())
        return result

    def as_dict(self) -> dict[str, Any]:
        def convert(value: Any) -> Any:
            if isinstance(value, SettingsModel):
                return {
                    model_field.name: convert(getattr(value, model_field.name))
                    for model_field in fields(value)
                }
            return value

        return convert(self)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> Self:
        def build(
            model_type: type[SettingsModel],
            model_values: dict[str, Any],
        ) -> SettingsModel:
            type_hints = get_type_hints(model_type)
            resolved: dict[str, Any] = {}
            for model_field in fields(model_type):
                value = model_values[model_field.name]
                field_type = type_hints[model_field.name]
                if isinstance(field_type, type) and issubclass(field_type, SettingsModel):
                    value = build(field_type, value)
                resolved[model_field.name] = value
            return model_type(**resolved)

        return cast(Self, build(cls, values))


class AppSettingsValue(Protocol):
    def get(self, key: str) -> Any: ...

    def keys(self) -> list[str]: ...

    def as_dict(self) -> dict[str, Any]: ...
