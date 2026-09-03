import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.extensions import get_all_extensions
from src.managers.extension_state_manager import ExtensionStateManager

from .base import BaseNodeMixin


class ExtensionNodeMixin(BaseNodeMixin):

    @classmethod
    def get_extension_state(cls, key: str = "default") -> dict[str, Any]:
        cls.ensure_extension_metadata()
        if not cls.EXTENSION_NAME:
            return {}

        return ExtensionStateManager.get_state(cls.EXTENSION_NAME, key=key)

    @classmethod
    def set_extension_state(cls, value: dict[str, Any], key: str = "default") -> dict[str, Any]:
        cls.ensure_extension_metadata()
        if not cls.EXTENSION_NAME:
            raise RuntimeError(f"Node '{cls.__name__}' is not bound to an extension.")

        return ExtensionStateManager.set_state(cls.EXTENSION_NAME, value=value, key=key)

    @classmethod
    def update_extension_state(
        cls,
        updater: Callable[[dict[str, Any]], dict[str, Any]],
        key: str = "default",
    ) -> dict[str, Any]:
        cls.ensure_extension_metadata()
        if not cls.EXTENSION_NAME:
            raise RuntimeError(f"Node '{cls.__name__}' is not bound to an extension.")

        return ExtensionStateManager.update_state(
            cls.EXTENSION_NAME,
            updater=updater,
            key=key,
        )

    @classmethod
    def ensure_extension_metadata(cls) -> None:
        if cls.EXTENSION_NAME:
            return

        extension_name = cls._resolve_extension_name_from_module()
        if extension_name:
            cls.EXTENSION_NAME = extension_name
            extension = get_all_extensions().get(extension_name)
            if extension and not cls.EXTENSION_VERSION:
                cls.EXTENSION_VERSION = extension.version
            return

        extension = cls._resolve_extension_from_path()
        if extension:
            cls.EXTENSION_NAME = extension.name
            if not cls.EXTENSION_VERSION:
                cls.EXTENSION_VERSION = extension.version

    @classmethod
    def _resolve_extension_name_from_module(cls) -> str | None:
        module_name = getattr(cls, "__module__", "")
        if not module_name.startswith("dvt_extensions."):
            return None

        from src.extensions.loader import extension_module_prefix

        extensions = get_all_extensions()
        for extension_name in extensions:
            prefix = extension_module_prefix(extension_name)
            if module_name == prefix or module_name.startswith(f"{prefix}."):
                return extension_name
        legacy_name = module_name.removeprefix("dvt_extensions.").split(".", 1)[0]
        return legacy_name if legacy_name in extensions else None

    @classmethod
    def _resolve_extension_from_path(cls):
        try:
            node_file = Path(inspect.getfile(cls)).resolve()
        except (TypeError, OSError):
            return None

        for extension in get_all_extensions().values():
            try:
                node_file.relative_to(extension.root_dir.resolve())
                return extension
            except ValueError:
                continue
        return None
