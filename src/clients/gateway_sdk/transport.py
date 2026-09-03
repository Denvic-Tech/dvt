from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote

import httpx
from pydantic import TypeAdapter

from .auth import AuthConfig, is_auth_sign_in_path, is_public_path
from .errors import DVTAPIError, DVTAuthError, DVTTransportError, DVTValidationError
from .models_extra import BinaryPayload, SignInResult


def _extract_access_token(payload: Any) -> str | None:
    if isinstance(payload, Mapping):
        for key in ("access_token", "accessToken"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        for nested_key in ("data", "tokens", "result"):
            nested_value = payload.get(nested_key)
            token = _extract_access_token(nested_value)
            if token:
                return token
    elif isinstance(payload, list):
        for item in payload:
            token = _extract_access_token(item)
            if token:
                return token
    return None


def _parse_json(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except json.JSONDecodeError:
        return None


def _extract_filename(headers: Mapping[str, str]) -> str | None:
    content_disposition = headers.get("content-disposition")
    if not content_disposition:
        return None
    for part in content_disposition.split(";"):
        part = part.strip()
        if part.startswith("filename*="):
            _, _, encoded = part.partition("''")
            return unquote(encoded) if encoded else None
        if part.startswith("filename="):
            return part.split("=", 1)[1].strip("\"")
    return None


class _TransportCommon:
    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 30.0,
        username: str | None = None,
        password: str | None = None,
        access_token: str | None = None,
        api_token: str | None = None,
        default_headers: Mapping[str, str] | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._auth = AuthConfig(
            username=username,
            password=password,
            access_token=access_token,
            api_token=api_token,
        )
        self._default_headers = dict(default_headers or {})

    def _auth_headers(self, path: str) -> dict[str, str]:
        headers: dict[str, str] = {}
        if is_public_path(path) and self._auth.api_token:
            headers["X-API-Key"] = self._auth.api_token
            return headers
        if self._auth.access_token:
            headers["Authorization"] = f"Bearer {self._auth.access_token}"
        return headers

    def _merge_headers(
        self,
        *,
        path: str,
        headers: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        merged = dict(self._default_headers)
        merged.update(self._auth_headers(path))
        for key, value in (headers or {}).items():
            merged[key] = str(value)
        return merged

    def _validate_response(self, response: httpx.Response) -> httpx.Response:
        if response.status_code < 400:
            return response

        payload = _parse_json(response)
        text = response.text
        hint = None
        if (
            response.status_code in {401, 403}
            and self._auth.api_token
            and not is_public_path(response.request.url.path)
            and not self._auth.access_token
        ):
            hint = "API token support is intended for /public routes. Use username/password or access_token."

        error_cls = DVTAPIError
        if response.status_code == 422:
            error_cls = DVTValidationError
        elif response.status_code in {401, 403}:
            error_cls = DVTAuthError

        raise error_cls(
            f"{response.request.method} {response.request.url.path} failed",
            status_code=response.status_code,
            method=response.request.method,
            path=response.request.url.path,
            response_text=text,
            response_json=payload if isinstance(payload, (dict, list)) else None,
            hint=hint,
        )

    def _parse_model(self, payload: Any, response_type: Any) -> Any:
        if response_type is None:
            return payload
        adapter = TypeAdapter(response_type)
        return adapter.validate_python(payload)


class DVTAsyncTransport(_TransportCommon):
    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            follow_redirects=True,
        )
        self._logged_in = False

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _ensure_auth(self, path: str) -> None:
        if is_auth_sign_in_path(path):
            return
        if is_public_path(path) and self._auth.api_token:
            return
        if self._auth.access_token:
            return
        if self._auth.has_username_password and not self._logged_in:
            await self.sign_in(username=self._auth.username, password=self._auth.password)

    async def sign_in(
        self,
        *,
        username: str | None = None,
        password: str | None = None,
    ) -> SignInResult:
        resolved_username = username or self._auth.username
        resolved_password = password or self._auth.password
        if not resolved_username or not resolved_password:
            raise DVTAuthError(
                "Missing username/password for sign-in",
                status_code=401,
                method="POST",
                path="/auth/sign-in",
            )

        try:
            response = await self._client.post(
                "/auth/sign-in",
                json={
                    "auth_provider": "email",
                    "email": resolved_username,
                    "password": resolved_password,
                },
            )
        except httpx.HTTPError as exc:
            raise DVTTransportError("Gateway sign-in request failed", cause=exc) from exc

        self._validate_response(response)
        payload = _parse_json(response)
        access_token = _extract_access_token(payload)
        if access_token:
            self._auth.access_token = access_token
        self._logged_in = True
        message = payload.get("message") if isinstance(payload, Mapping) else None
        success = bool(payload.get("success", True)) if isinstance(payload, Mapping) else True
        return SignInResult(
            success=success,
            message=message if isinstance(message, str) else None,
            access_token=access_token,
            payload=payload if isinstance(payload, (dict, list)) else None,
        )

    async def _request(
        self,
        *,
        method: str,
        path: str,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        await self._ensure_auth(path)
        try:
            response = await self._client.request(
                method=method,
                url=path,
                params=query or None,
                headers=self._merge_headers(path=path, headers=headers),
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise DVTTransportError(
                f"Gateway request failed: {method.upper()} {path}",
                cause=exc,
            ) from exc
        return self._validate_response(response)

    async def request_json(
        self,
        *,
        method: str,
        path: str,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        json_data: Any = None,
        response_type: Any = None,
        unwrap_data: bool = False,
        **kwargs: Any,
    ) -> Any:
        response = await self._request(
            method=method,
            path=path,
            query=query,
            headers=headers,
            json=json_data,
            **kwargs,
        )
        payload = _parse_json(response)
        if unwrap_data and isinstance(payload, Mapping) and "data" in payload:
            payload = payload.get("data")
        return self._parse_model(payload, response_type)

    async def request_text(
        self,
        *,
        method: str,
        path: str,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
    ) -> str:
        response = await self._request(method=method, path=path, query=query, headers=headers)
        return response.text

    async def request_binary(
        self,
        *,
        method: str,
        path: str,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
    ) -> BinaryPayload:
        response = await self._request(method=method, path=path, query=query, headers=headers)
        return BinaryPayload(
            content=response.content,
            content_type=response.headers.get("content-type"),
            filename=_extract_filename(response.headers),
            headers=dict(response.headers),
        )


class DVTSyncTransport(_TransportCommon):
    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout,
            follow_redirects=True,
        )
        self._logged_in = False

    def close(self) -> None:
        self._client.close()

    def _ensure_auth(self, path: str) -> None:
        if is_auth_sign_in_path(path):
            return
        if is_public_path(path) and self._auth.api_token:
            return
        if self._auth.access_token:
            return
        if self._auth.has_username_password and not self._logged_in:
            self.sign_in(username=self._auth.username, password=self._auth.password)

    def sign_in(
        self,
        *,
        username: str | None = None,
        password: str | None = None,
    ) -> SignInResult:
        resolved_username = username or self._auth.username
        resolved_password = password or self._auth.password
        if not resolved_username or not resolved_password:
            raise DVTAuthError(
                "Missing username/password for sign-in",
                status_code=401,
                method="POST",
                path="/auth/sign-in",
            )

        try:
            response = self._client.post(
                "/auth/sign-in",
                json={
                    "auth_provider": "email",
                    "email": resolved_username,
                    "password": resolved_password,
                },
            )
        except httpx.HTTPError as exc:
            raise DVTTransportError("Gateway sign-in request failed", cause=exc) from exc

        self._validate_response(response)
        payload = _parse_json(response)
        access_token = _extract_access_token(payload)
        if access_token:
            self._auth.access_token = access_token
        self._logged_in = True
        message = payload.get("message") if isinstance(payload, Mapping) else None
        success = bool(payload.get("success", True)) if isinstance(payload, Mapping) else True
        return SignInResult(
            success=success,
            message=message if isinstance(message, str) else None,
            access_token=access_token,
            payload=payload if isinstance(payload, (dict, list)) else None,
        )

    def _request(
        self,
        *,
        method: str,
        path: str,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        self._ensure_auth(path)
        try:
            response = self._client.request(
                method=method,
                url=path,
                params=query or None,
                headers=self._merge_headers(path=path, headers=headers),
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise DVTTransportError(
                f"Gateway request failed: {method.upper()} {path}",
                cause=exc,
            ) from exc
        return self._validate_response(response)

    def request_json(
        self,
        *,
        method: str,
        path: str,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        json_data: Any = None,
        response_type: Any = None,
        unwrap_data: bool = False,
        **kwargs: Any,
    ) -> Any:
        response = self._request(
            method=method,
            path=path,
            query=query,
            headers=headers,
            json=json_data,
            **kwargs,
        )
        payload = _parse_json(response)
        if unwrap_data and isinstance(payload, Mapping) and "data" in payload:
            payload = payload.get("data")
        return self._parse_model(payload, response_type)

    def request_text(
        self,
        *,
        method: str,
        path: str,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
    ) -> str:
        response = self._request(method=method, path=path, query=query, headers=headers)
        return response.text

    def request_binary(
        self,
        *,
        method: str,
        path: str,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
    ) -> BinaryPayload:
        response = self._request(method=method, path=path, query=query, headers=headers)
        return BinaryPayload(
            content=response.content,
            content_type=response.headers.get("content-type"),
            filename=_extract_filename(response.headers),
            headers=dict(response.headers),
        )
