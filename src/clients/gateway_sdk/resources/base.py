from __future__ import annotations

from collections.abc import Mapping
from inspect import isclass
from typing import Any, get_type_hints
from urllib.parse import quote

from pydantic import BaseModel


def _serialize_data(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, Mapping):
        return {key: _serialize_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_serialize_data(item) for item in value]
    return value


def _clean_mapping(items: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in items.items():
        if value is None:
            continue
        cleaned[key] = _serialize_data(value)
    return cleaned


def _render_path(template: str, path_params: Mapping[str, Any]) -> str:
    rendered = template
    for key, value in path_params.items():
        rendered = rendered.replace(f"{{{key}}}", quote(str(value), safe=""))
    return rendered


def _init_typed_resources(instance: Any, transport: Any, base_type: type[Any]) -> None:
    hints = get_type_hints(instance.__class__)

    for attr_name, attr_type in hints.items():
        if attr_name.startswith("_"):
            continue

        if not isclass(attr_type):
            continue

        if not issubclass(attr_type, base_type):
            continue

        # чтобы не перезатирать ресурс, если его уже руками выставили
        if attr_name in instance.__dict__:
            continue

        setattr(instance, attr_name, attr_type(transport))


class AsyncResourceInitializerMixin:
    def _init_resources(self, transport) -> None:
        _init_typed_resources(self, transport, AsyncResourceBase)


class AsyncResourceBase(AsyncResourceInitializerMixin):
    def __init__(self, transport):
        self._transport = transport
        self._init_resources(transport)

    async def _request_json(
        self,
        *,
        method: str,
        path: str,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        data: Any = None,
        response_type: Any = None,
        unwrap_data: bool = False,
    ) -> Any:
        return await self._transport.request_json(
            method=method,
            path=_render_path(path, path_params or {}),
            query=_clean_mapping(query or {}),
            headers=_clean_mapping(headers or {}),
            json_data=_serialize_data(data),
            response_type=response_type,
            unwrap_data=unwrap_data,
        )

    async def _request_text(
        self,
        *,
        method: str,
        path: str,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
    ) -> str:
        return await self._transport.request_text(
            method=method,
            path=_render_path(path, path_params or {}),
            query=_clean_mapping(query or {}),
            headers=_clean_mapping(headers or {}),
        )

    async def _request_binary(
        self,
        *,
        method: str,
        path: str,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
    ):
        return await self._transport.request_binary(
            method=method,
            path=_render_path(path, path_params or {}),
            query=_clean_mapping(query or {}),
            headers=_clean_mapping(headers or {}),
        )

    async def _request_content(
        self,
        *,
        method: str,
        path: str,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        content: str | bytes | None = None,
        response_type: Any = None,
    ) -> Any:
        return await self._transport.request_json(
            method=method,
            path=_render_path(path, path_params or {}),
            query=_clean_mapping(query or {}),
            headers=_clean_mapping(headers or {}),
            content=content,
            response_type=response_type,
        )

    async def _request_multipart(
        self,
        *,
        method: str,
        path: str,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        form_data: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
        response_type: Any = None,
        unwrap_data: bool = False,
    ) -> Any:
        return await self._transport.request_json(
            method=method,
            path=_render_path(path, path_params or {}),
            query=_clean_mapping(query or {}),
            headers=_clean_mapping(headers or {}),
            data=_clean_mapping(form_data or {}),
            files=files,
            response_type=response_type,
            unwrap_data=unwrap_data,
        )


class SyncResourceInitializerMixin:
    def _init_resources(self, transport) -> None:
        _init_typed_resources(self, transport, SyncResourceBase)


class SyncResourceBase(SyncResourceInitializerMixin):
    def __init__(self, transport):
        self._transport = transport
        self._init_resources(transport)

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        data: Any = None,
        response_type: Any = None,
        unwrap_data: bool = False,
    ) -> Any:
        return self._transport.request_json(
            method=method,
            path=_render_path(path, path_params or {}),
            query=_clean_mapping(query or {}),
            headers=_clean_mapping(headers or {}),
            json_data=_serialize_data(data),
            response_type=response_type,
            unwrap_data=unwrap_data,
        )

    def _request_text(
        self,
        *,
        method: str,
        path: str,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
    ) -> str:
        return self._transport.request_text(
            method=method,
            path=_render_path(path, path_params or {}),
            query=_clean_mapping(query or {}),
            headers=_clean_mapping(headers or {}),
        )

    def _request_binary(
        self,
        *,
        method: str,
        path: str,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
    ):
        return self._transport.request_binary(
            method=method,
            path=_render_path(path, path_params or {}),
            query=_clean_mapping(query or {}),
            headers=_clean_mapping(headers or {}),
        )

    def _request_content(
        self,
        *,
        method: str,
        path: str,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        content: str | bytes | None = None,
        response_type: Any = None,
    ) -> Any:
        return self._transport.request_json(
            method=method,
            path=_render_path(path, path_params or {}),
            query=_clean_mapping(query or {}),
            headers=_clean_mapping(headers or {}),
            content=content,
            response_type=response_type,
        )

    def _request_multipart(
        self,
        *,
        method: str,
        path: str,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        form_data: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
        response_type: Any = None,
        unwrap_data: bool = False,
    ) -> Any:
        return self._transport.request_json(
            method=method,
            path=_render_path(path, path_params or {}),
            query=_clean_mapping(query or {}),
            headers=_clean_mapping(headers or {}),
            data=_clean_mapping(form_data or {}),
            files=files,
            response_type=response_type,
            unwrap_data=unwrap_data,
        )
