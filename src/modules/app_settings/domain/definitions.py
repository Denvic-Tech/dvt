from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, dataclass_transform

_MISSING = object()
_SETTING_METADATA_KEY = "app_setting"


@dataclass(frozen=True)
class Setting:
    type_: Any
    default: Any = _MISSING
    default_factory: Callable[[], Any] | None = None
    ge: int | float | None = None
    le: int | float | None = None
    min_length: int | None = None
    max_length: int | None = None
    description: str | None = None
    secret: bool = False
    runtime_editable: bool = True
    bootstrap: bool = False
    required: bool = False
    read_env: bool = False
    env_var: str | None = None
    setup_label: str | None = None
    setup_type: str | None = None

    def get_default(self) -> Any:
        if self.default_factory is not None:
            return self.default_factory()
        if self.default is not _MISSING:
            return self.default
        return None


def setting(
    *,
    default: Any = _MISSING,
    default_factory: Callable[[], Any] | None = None,
    ge: int | float | None = None,
    le: int | float | None = None,
    min_length: int | None = None,
    max_length: int | None = None,
    description: str | None = None,
    secret: bool = False,
    runtime_editable: bool = True,
    bootstrap: bool = False,
    required: bool = False,
    read_env: bool = False,
    env_var: str | None = None,
    setup_label: str | None = None,
    setup_type: str | None = None,
) -> Any:
    definition = Setting(
        type_=Any,
        default=default,
        default_factory=default_factory,
        ge=ge,
        le=le,
        min_length=min_length,
        max_length=max_length,
        description=description,
        secret=secret,
        runtime_editable=runtime_editable,
        bootstrap=bootstrap,
        required=required,
        read_env=read_env,
        env_var=env_var,
        setup_label=setup_label,
        setup_type=setup_type,
    )
    field_kwargs: dict[str, Any] = {
        "metadata": {_SETTING_METADATA_KEY: definition},
    }
    if default_factory is not None:
        field_kwargs["default_factory"] = default_factory
    elif default is not _MISSING:
        field_kwargs["default"] = default
    return field(**field_kwargs)


@dataclass_transform(field_specifiers=(setting,), frozen_default=True)
class SettingsModel:
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        dataclass(cls, frozen=True)


class SettingGroup:
    def __init__(self, **settings: Setting) -> None:
        self.settings = dict(settings)


class SettingsNamespace:
    def __init__(self, **items: Setting | SettingGroup) -> None:
        self.items = dict(items)


@dataclass(frozen=True)
class SettingDefinition:
    namespace: str
    group: str | None
    name: str
    type_: Any
    default: Any
    ge: int | float | None
    le: int | float | None
    min_length: int | None
    max_length: int | None
    description: str | None
    secret: bool
    runtime_editable: bool
    bootstrap: bool
    required: bool
    read_env: bool
    env_var: str | None
    setup_label: str | None
    setup_type: str | None

    @property
    def key(self) -> str:
        if self.group is not None:
            return f"{self.namespace}.{self.group}.{self.name}"
        return f"{self.namespace}.{self.name}"
