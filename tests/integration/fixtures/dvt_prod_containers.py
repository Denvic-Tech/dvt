from __future__ import annotations

import socket
import time
from typing import Any, Generator

import pytest
import requests
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

from .settings import IntegrationTestSettings
import contextlib


def _read_container_logs(container: DockerContainer) -> str:
    wrapped = container.get_wrapped_container()
    try:
        return wrapped.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover
        return f"<failed to read logs: {exc}>"


def wait_port(container: DockerContainer, internal_port: int, *, timeout: int = 180) -> None:
    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(internal_port))

    deadline = time.monotonic() + timeout
    last_err: Exception | None = None

    while time.monotonic() < deadline:
        wrapped = container.get_wrapped_container()
        try:
            wrapped.reload()
        except Exception:
            pass

        status = getattr(wrapped, "status", None)
        if status in ("exited", "dead"):
            logs = _read_container_logs(container)
            raise RuntimeError(
                f"Container died while waiting for port {host}:{port}. status={status}\n"
                f"\n--- container logs ---\n{logs}\n"
            )

        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError as exc:
            last_err = exc
            time.sleep(1)

    logs = _read_container_logs(container)
    raise TimeoutError(
        f"Port {host}:{port} not open after {timeout}s. last_err={last_err}\n"
        f"\n--- container logs ---\n{logs}\n"
    )


def wait_http(
    container: DockerContainer,
    internal_port: int,
    *,
    path: str = "/",
    timeout: int = 180,
    request_timeout: int = 3,
) -> None:
    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(internal_port))
    url = f"http://{host}:{port}{path if path.startswith('/') else '/' + path}"

    deadline = time.monotonic() + timeout
    last_err: Exception | None = None

    while time.monotonic() < deadline:
        wrapped = container.get_wrapped_container()
        with contextlib.suppress(Exception):
            wrapped.reload()

        status = getattr(wrapped, "status", None)
        if status in ("exited", "dead"):
            logs = _read_container_logs(container)
            raise RuntimeError(
                f"Container died while waiting for HTTP {url}. status={status}\n"
                f"\n--- container logs ---\n{logs}\n"
            )

        try:
            requests.get(url, timeout=request_timeout).raise_for_status()
            return
        except requests.RequestException as exc:
            last_err = exc
            time.sleep(1)

    logs = _read_container_logs(container)
    raise TimeoutError(
        f"HTTP {url} not responding after {timeout}s. last_err={last_err}\n"
        f"\n--- container logs ---\n{logs}\n"
    )


def wait_running(container: DockerContainer, *, timeout: int = 180, stable_sec: int = 5) -> None:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None

    while time.monotonic() < deadline:
        wrapped = container.get_wrapped_container()
        try:
            wrapped.reload()
        except Exception:
            pass

        status = getattr(wrapped, "status", None)
        if status in ("exited", "dead"):
            logs = _read_container_logs(container)
            raise RuntimeError(
                f"Container died while waiting to stay running for {stable_sec}s. status={status}\n"
                f"\n--- container logs ---\n{logs}\n"
            )

        if status == "running":
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= stable_sec:
                return
        else:
            stable_since = None

        time.sleep(1)

    logs = _read_container_logs(container)
    raise TimeoutError(
        f"Container did not stay running for {stable_sec}s within {timeout}s.\n"
        f"\n--- container logs ---\n{logs}\n"
    )


@pytest.fixture(scope="session")
def dvt_network() -> Generator[Network, Any, None]:
    with Network() as network:
        yield network


@pytest.fixture(scope="session")
def dvt_postgres_container(dvt_network: Network) -> Generator[DockerContainer, Any, None]:
    with (
        DockerContainer("postgres:15.3-alpine")
        .with_network(dvt_network)
        .with_network_aliases("postgres")
        .with_env("POSTGRES_USER", "postgres")
        .with_env("POSTGRES_PASSWORD", "postgres")
        .with_env("POSTGRES_DB", "DVT")
        .with_exposed_ports(5432)
    ) as container:
        wait_port(container, 5432, timeout=180)
        yield container


@pytest.fixture(scope="session")
def dvt_valkey_container(dvt_network: Network) -> Generator[DockerContainer, Any, None]:
    with (
        DockerContainer("valkey/valkey:7.2-alpine")
        .with_network(dvt_network)
        .with_network_aliases("valkey")
        .with_env("VALKEY_PASSWORD", "valkeypass")
        .with_command(
            'valkey-server --save "" --appendonly no --loglevel warning --requirepass valkeypass'
        )
        .with_exposed_ports(6379)
    ) as container:
        wait_port(container, 6379, timeout=180)
        yield container


@pytest.fixture(scope="session")
def orchestrator_container(
    dvt_network: Network,
    dvt_postgres_container: DockerContainer,
    dvt_valkey_container: DockerContainer,
    test_dvt_db_engine: Any,
    integration_test_settings: IntegrationTestSettings,
) -> Generator[DockerContainer, Any, None]:
    with (
        DockerContainer(integration_test_settings.dvt_image("orchestrator"))
        .with_network(dvt_network)
        .with_network_aliases("orchestrator")
        .with_env("POSTGRES_HOST", "postgres")
        .with_env("POSTGRES_PORT", "5432")
        .with_env("POSTGRES_USER", "postgres")
        .with_env("POSTGRES_PASSWORD", "postgres")
        .with_env("POSTGRES_DB", "DVT")
        .with_env("ORCHESTRATOR_HOST", "0.0.0.0")
        .with_env("ORCHESTRATOR_PORT", "8250")
        .with_env("VALKEY_HOST", "valkey")
        .with_env("VALKEY_PORT", "6379")
        .with_env("VALKEY_PASSWORD", "valkeypass")
        .with_env("VALKEY_DB", "0")
        .with_env("GRPC_FORWARD_SERVICE_HOST", "gateway")
        .with_env("GRPC_FORWARD_SERVICE_PORT", "50561")
        .with_env("GRPC_FORWARD_SERVICE_TOKEN", "forward-secret-token")
        .with_exposed_ports(8250)
    ) as container:
        wait_port(container, 8250, timeout=180)
        yield container


@pytest.fixture(scope="session")
def task_worker_container(
    dvt_network: Network,
    dvt_postgres_container: DockerContainer,
    dvt_valkey_container: DockerContainer,
    orchestrator_container: DockerContainer,
    integration_test_settings: IntegrationTestSettings,
) -> Generator[DockerContainer, Any, None]:
    with (
        DockerContainer(integration_test_settings.dvt_image("task-worker"))
        .with_network(dvt_network)
        .with_network_aliases("task-worker")
        .with_env("POSTGRES_HOST", "postgres")
        .with_env("POSTGRES_PORT", "5432")
        .with_env("POSTGRES_USER", "postgres")
        .with_env("POSTGRES_PASSWORD", "postgres")
        .with_env("POSTGRES_DB", "DVT")
        .with_env("LICENSE_CLIENT_TYPE", "dvt")
        .with_env("GATEWAY_HOST", "gateway")
        .with_env("GATEWAY_PORT", "8000")
        .with_env("TASK_WORKER_HOST", "0.0.0.0")
        .with_env("TASK_WORKER_PORT", "8000")
        .with_env("DISABLE_STORE", "false")
        .with_env("GRPC_FORWARD_SERVICE_HOST", "gateway")
        .with_env("GRPC_FORWARD_SERVICE_PORT", "50561")
        .with_env("GRPC_FORWARD_SERVICE_TOKEN", "forward-secret-token")
        .with_env("VALKEY_HOST", "valkey")
        .with_env("VALKEY_PORT", "6379")
        .with_env("VALKEY_PASSWORD", "valkeypass")
        .with_env("VALKEY_DB", "0")
    ) as container:
        wait_running(container, timeout=180, stable_sec=5)
        yield container


@pytest.fixture(scope="session")
def project_scheduler_container(
    dvt_network: Network,
    dvt_postgres_container: DockerContainer,
    dvt_valkey_container: DockerContainer,
    orchestrator_container: DockerContainer,
    gateway_container: DockerContainer,
    integration_test_settings: IntegrationTestSettings,
) -> Generator[DockerContainer, Any, None]:
    with (
        DockerContainer(integration_test_settings.dvt_image("project-scheduler"))
        .with_network(dvt_network)
        .with_network_aliases("project-scheduler")
        .with_env("POSTGRES_HOST", "postgres")
        .with_env("POSTGRES_PORT", "5432")
        .with_env("POSTGRES_USER", "postgres")
        .with_env("POSTGRES_PASSWORD", "postgres")
        .with_env("POSTGRES_DB", "DVT")
        .with_env("ORCHESTRATOR_HOST", "orchestrator")
        .with_env("ORCHESTRATOR_PORT", "8250")
        .with_env("VALKEY_HOST", "valkey")
        .with_env("VALKEY_PORT", "6379")
        .with_env("VALKEY_PASSWORD", "valkeypass")
        .with_env("VALKEY_DB", "0")
        .with_env("GRPC_FORWARD_SERVICE_HOST", "0.0.0.0")
        .with_env("GRPC_FORWARD_SERVICE_PORT", "50561")
        .with_env("GRPC_FORWARD_SERVICE_TOKEN", "forward-secret-token")
        .with_env("LICENSE_CLIENT_TYPE", "dvt")
        .with_env("PROJECT_SCHEDULER_HOST", "0.0.0.0")
        .with_env("PROJECT_SCHEDULER_PORT", "8000")
        .with_env("FERNET_KEY", integration_test_settings.fernet_key)
        .with_exposed_ports(8000)
    ) as container:
        wait_port(container, 8000, timeout=180)
        yield container


@pytest.fixture(scope="session")
def gateway_container(
    dvt_network: Network,
    dvt_postgres_container: DockerContainer,
    dvt_valkey_container: DockerContainer,
    orchestrator_container: DockerContainer,
    integration_test_settings: IntegrationTestSettings,
) -> Generator[DockerContainer, Any, None]:
    with (
        DockerContainer(integration_test_settings.dvt_image("gateway"))
        .with_network(dvt_network)
        .with_network_aliases("gateway")
        .with_env("POSTGRES_HOST", "postgres")
        .with_env("POSTGRES_PORT", "5432")
        .with_env("POSTGRES_USER", "postgres")
        .with_env("POSTGRES_PASSWORD", "postgres")
        .with_env("POSTGRES_DB", "DVT")
        .with_env("VALKEY_HOST", "valkey")
        .with_env("VALKEY_PORT", "6379")
        .with_env("VALKEY_PASSWORD", "valkeypass")
        .with_env("VALKEY_DB", "0")
        .with_env("GATEWAY_HOST", "0.0.0.0")
        .with_env("GATEWAY_PORT", "8000")
        .with_env("ORCHESTRATOR_HOST", "orchestrator")
        .with_env("ORCHESTRATOR_PORT", "8250")
        .with_env("GRPC_FORWARD_SERVICE_HOST", "0.0.0.0")
        .with_env("GRPC_FORWARD_SERVICE_PORT", "50561")
        .with_env("GRPC_FORWARD_SERVICE_TOKEN", "forward-secret-token")
        .with_env("GATEWAY_ORIGINS", integration_test_settings.gateway_origins)
        .with_env("GATEWAY_COOKIE_SECURE", "false")
        .with_env("LICENSE_CLIENT_TYPE", "dvt")
        .with_env("PROJECT_SCHEDULER_HOST", "project-scheduler")
        .with_env("PROJECT_SCHEDULER_PORT", "8000")
        .with_env("FERNET_KEY", integration_test_settings.fernet_key)
        .with_env("DEFAULT_PASSWORD", integration_test_settings.default_password)
        .with_env("DEFAULT_EMAIL", integration_test_settings.default_email)
        .with_exposed_ports(8000, 50561)
    ) as container:
        wait_http(container, 8000, path="/api/setup/status", timeout=300)
        yield container
