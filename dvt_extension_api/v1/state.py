"""Persistent extension state facade."""

from collections.abc import Callable
from typing import Any

from src.managers.extension_state_manager import ExtensionStateManager


def get_extension_state(extension_name: str, key: str = "default") -> dict[str, Any]:
    return ExtensionStateManager.get_state(extension_name, key=key)


def set_extension_state(
    extension_name: str, value: dict[str, Any], key: str = "default"
) -> dict[str, Any]:
    return ExtensionStateManager.set_state(extension_name, value=value, key=key)


def update_extension_state(
    extension_name: str,
    updater: Callable[[dict[str, Any]], dict[str, Any]],
    key: str = "default",
) -> dict[str, Any]:
    return ExtensionStateManager.update_state(extension_name, updater=updater, key=key)


async def async_get_extension_state(extension_name: str, key: str = "default") -> dict[str, Any]:
    return await ExtensionStateManager.async_get_state(extension_name, key=key)


async def async_set_extension_state(
    extension_name: str, value: dict[str, Any], key: str = "default"
) -> dict[str, Any]:
    return await ExtensionStateManager.async_set_state(extension_name, value=value, key=key)


async def async_update_extension_state(
    extension_name: str,
    updater: Callable[[dict[str, Any]], dict[str, Any]],
    key: str = "default",
) -> dict[str, Any]:
    return await ExtensionStateManager.async_update_state(
        extension_name, updater=updater, key=key
    )


__all__ = [
    "async_get_extension_state",
    "async_set_extension_state",
    "async_update_extension_state",
    "get_extension_state",
    "set_extension_state",
    "update_extension_state",
]
