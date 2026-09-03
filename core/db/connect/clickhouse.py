from __future__ import annotations

import atexit
import logging
import os
import threading
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

import clickhouse_connect
from clickhouse_connect.driver import httputil
from clickhouse_connect.driver.client import Client
from sqlalchemy import Engine
from urllib3.poolmanager import PoolManager

logger = logging.getLogger(__name__)

_HTTP_POOL_MAXSIZE_ENV = "CLICKHOUSE_HTTP_POOL_MAXSIZE"
_DEFAULT_HTTP_POOL_MAXSIZE = 8

_GENERIC_TRANSPORT_KEYS = frozenset(
    {
        "verify",
        "ca_cert",
        "client_cert",
        "client_cert_key",
        "http_proxy",
        "https_proxy",
        "server_host_name",
    }
)


def _http_pool_maxsize() -> int:
    value = int(os.getenv(_HTTP_POOL_MAXSIZE_ENV, str(_DEFAULT_HTTP_POOL_MAXSIZE)))
    if value <= 0:
        raise ValueError(f"{_HTTP_POOL_MAXSIZE_ENV} must be a positive integer")
    return value


@dataclass(frozen=True)
class _TransportProfile:
    pid: int
    interface: str
    verify: bool
    ca_cert: str | None
    client_cert: str | None
    client_cert_key: str | None
    server_host_name: str | None
    proxy_kind: str | None
    proxy_url: str | None


@dataclass
class _PoolManagerRegistry:
    pid: int
    lock: Any
    managers: dict[_TransportProfile, PoolManager]


@dataclass
class _PoolManagerRegistryRef:
    current: _PoolManagerRegistry
    reset_lock: Any


_registry = _PoolManagerRegistryRef(
    current=_PoolManagerRegistry(pid=os.getpid(), lock=threading.Lock(), managers={}),
    reset_lock=threading.Lock(),
)


def _optional_string(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    return str(value)


def _coerce_verify(value: Any) -> bool:
    if isinstance(value, str):
        value = value.lower()
        if value == "proxy":
            return True
        return value in {"true", "1", "y", "yes"}
    return value is True


def _normalise_proxy(proxy: Any, scheme: str) -> str | None:
    proxy_url = _optional_string(proxy)
    if not proxy_url:
        return None
    lower_proxy_url = proxy_url.lower()
    if lower_proxy_url.startswith("http://"):
        return f"http://{proxy_url[7:]}"
    if lower_proxy_url.startswith("https://"):
        return f"https://{proxy_url[8:]}"
    return f"{scheme}://{proxy_url}"


def _dsn_transport_values(client_kwargs: Mapping[str, Any]) -> tuple[Any, Any, dict[str, Any]]:
    dsn = client_kwargs.get("dsn")
    if not dsn:
        return None, None, {}

    parsed = urlparse(str(dsn))
    query = {key: values[0] for key, values in parse_qs(parsed.query).items() if values}
    return parsed.hostname, parsed.port, query


def _effective_proxy(
    scheme: str,
    host: str,
    port: Any,
    transport_kwargs: Mapping[str, Any],
) -> str | None:
    explicit_proxy = transport_kwargs.get(f"{scheme}_proxy")
    if explicit_proxy:
        return _normalise_proxy(explicit_proxy, scheme)
    return _normalise_proxy(httputil.check_env_proxy(scheme, host, port), scheme)


def _pool_manager_spec(
    client_kwargs: Mapping[str, Any],
) -> tuple[_TransportProfile, dict[str, Any]]:
    dsn_host, dsn_port, dsn_query = _dsn_transport_values(client_kwargs)
    if "pool_mgr" in dsn_query:
        raise ValueError("pool_mgr is managed by DVT and must not be supplied in the DSN")

    transport_kwargs = dict(client_kwargs)
    transport_kwargs.update(dsn_query)
    generic_args = client_kwargs.get("generic_args")
    if isinstance(generic_args, Mapping):
        if "pool_mgr" in generic_args:
            raise ValueError(
                "pool_mgr is managed by DVT and must not be supplied in generic_args"
            )
        for key in _GENERIC_TRANSPORT_KEYS:
            if key in generic_args:
                transport_kwargs[key] = generic_args[key]

    host = _optional_string(client_kwargs.get("host") or dsn_host) or "localhost"
    raw_port = client_kwargs.get("port") or dsn_port or 0
    raw_interface = client_kwargs.get("interface")
    secure = str(client_kwargs.get("secure", False)).lower() == "true"
    use_tls = (
        secure
        or raw_interface == "https"
        or (not raw_interface and str(raw_port) in {"443", "8443"})
    )
    interface = str(raw_interface or ("https" if use_tls else "http")).lower()
    port = raw_port or (8443 if use_tls else 8123)

    verify = _coerce_verify(transport_kwargs.get("verify", True))
    ca_cert = _optional_string(transport_kwargs.get("ca_cert"))
    client_cert = _optional_string(transport_kwargs.get("client_cert"))
    client_cert_key = _optional_string(transport_kwargs.get("client_cert_key"))
    server_host_name = _optional_string(transport_kwargs.get("server_host_name"))
    if server_host_name:
        server_host_name = server_host_name.lower()

    proxy_kind: str | None = None
    proxy_url: str | None = None
    manager_kwargs: dict[str, Any] = {
        "maxsize": _http_pool_maxsize(),
        "block": True,
    }

    if interface == "https":
        https_proxy = _effective_proxy("https", host, port, transport_kwargs)
        custom_https_manager = bool(
            server_host_name or ca_cert or client_cert or not verify or https_proxy
        )
        if custom_https_manager:
            proxy_kind = "https" if https_proxy else None
            proxy_url = https_proxy
        else:
            # This mirrors HttpClient: with default TLS options and no HTTPS proxy it
            # falls through to the generic HTTP proxy lookup.
            http_proxy = _effective_proxy("http", host, port, transport_kwargs)
            proxy_kind = "http" if http_proxy else None
            proxy_url = http_proxy

        manager_kwargs["verify"] = verify
        if ca_cert:
            manager_kwargs["ca_cert"] = ca_cert
        if client_cert:
            manager_kwargs["client_cert"] = client_cert
        if client_cert_key:
            manager_kwargs["client_cert_key"] = client_cert_key
        if server_host_name:
            if verify:
                manager_kwargs["assert_hostname"] = server_host_name
            manager_kwargs["server_hostname"] = server_host_name
    else:
        http_proxy = _effective_proxy("http", host, port, transport_kwargs)
        proxy_kind = "http" if http_proxy else None
        proxy_url = http_proxy
        verify = True
        ca_cert = client_cert = client_cert_key = server_host_name = None

    if proxy_kind == "http":
        manager_kwargs["http_proxy"] = proxy_url
    elif proxy_kind == "https":
        manager_kwargs["https_proxy"] = proxy_url

    profile = _TransportProfile(
        pid=os.getpid(),
        interface=interface,
        verify=verify,
        ca_cert=ca_cert,
        client_cert=client_cert,
        client_cert_key=client_cert_key,
        server_host_name=server_host_name,
        proxy_kind=proxy_kind,
        proxy_url=proxy_url,
    )
    return profile, manager_kwargs


def _close_managers(managers: tuple[PoolManager, ...]) -> None:
    for manager in managers:
        try:
            manager.clear()
        except Exception:  # pragma: no cover - defensive cleanup during shutdown
            logger.exception("Failed to close a ClickHouse HTTP pool manager")
        finally:
            try:
                httputil.all_managers.pop(manager, None)
            except Exception:  # pragma: no cover - interpreter shutdown safety
                logger.exception("Failed to unregister a ClickHouse HTTP pool manager")


def _unregister_inherited_managers(managers: tuple[PoolManager, ...]) -> None:
    # Calling PoolManager.clear() after fork can deadlock on an urllib3 lock that
    # was held by a vanished parent thread. Dropping DVT/all_managers ownership is
    # enough to prevent reuse; CPython then releases unreferenced inherited FDs.
    for manager in managers:
        with suppress(Exception):
            httputil.all_managers.pop(manager, None)


def _replace_registry_for_current_process() -> _PoolManagerRegistry:
    inherited_registry = _registry.current
    inherited_managers = tuple(inherited_registry.managers.values())
    registry = _PoolManagerRegistry(
        pid=os.getpid(),
        lock=threading.Lock(),
        managers={},
    )
    _registry.current = registry
    inherited_registry.managers.clear()
    _unregister_inherited_managers(inherited_managers)
    return registry


def _reset_pool_manager_registry_after_fork() -> None:
    # Any lock inherited from a multi-threaded parent might remain permanently
    # locked in the child, so publish fresh synchronization primitives first.
    _registry.reset_lock = threading.Lock()
    _replace_registry_for_current_process()


def _current_process_registry() -> _PoolManagerRegistry:
    registry = _registry.current
    if registry.pid == os.getpid():
        return registry

    with _registry.reset_lock:
        registry = _registry.current
        if registry.pid != os.getpid():
            registry = _replace_registry_for_current_process()
        return registry


def _get_pool_manager(client_kwargs: Mapping[str, Any]) -> PoolManager:
    registry = _current_process_registry()
    profile, manager_kwargs = _pool_manager_spec(client_kwargs)
    with registry.lock:
        manager = registry.managers.get(profile)
        if manager is None:
            manager = httputil.get_pool_manager(**manager_kwargs)
            registry.managers[profile] = manager
        return manager


def create_clickhouse_client(client_kwargs: Mapping[str, Any]) -> Client:
    """Create a ClickHouse client backed by a bounded process-local HTTP pool."""
    if "pool_mgr" in client_kwargs:
        raise ValueError("pool_mgr is managed by DVT and must not be supplied")

    kwargs = dict(client_kwargs)
    kwargs["pool_mgr"] = _get_pool_manager(kwargs)
    return clickhouse_connect.get_client(**kwargs)


def close_clickhouse_pool_managers() -> None:
    """Close and unregister all HTTP managers owned by DVT in this process."""
    registry = _current_process_registry()
    with registry.lock:
        managers = tuple(registry.managers.values())
        registry.managers.clear()

    _close_managers(managers)


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_pool_manager_registry_after_fork)
atexit.register(close_clickhouse_pool_managers)


def _bool_from_query(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return str(value).lower() in {"1", "true", "yes", "on"}


def build_clickhouse_client_kwargs(engine: Engine) -> dict[str, Any]:
    url = engine.url
    driver = (url.drivername or "").lower()
    interface = url.query.get("protocol") if url.query else None
    if not interface:
        interface = "native" if "native" in driver else "http"
    secure = _bool_from_query(url.query.get("secure")) if url.query else False

    port = url.port
    if port is None:
        port = 9000 if interface == "native" else (8443 if secure else 8123)

    client_kwargs: dict[str, Any] = {
        "host": url.host or "localhost",
        "port": port,
        "username": url.username or "default",
        "password": url.password or "",
        "database": url.database,
        "secure": secure,
        "interface": interface,
    }

    # Extra client arguments coming from URL query parameters
    for key in ("verify", "client_name"):
        if url.query and key in url.query:
            client_kwargs[key] = url.query[key]

    default_settings: dict[str, Any] = {}
    for key in ("connect_timeout", "send_receive_timeout", "compression"):
        if url.query and key in url.query:
            raw_val = url.query[key]
            try:
                default_settings[key] = int(raw_val)
            except (TypeError, ValueError):
                default_settings[key] = raw_val

    if default_settings:
        client_kwargs["settings"] = default_settings

    return client_kwargs
