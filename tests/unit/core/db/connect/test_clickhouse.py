import multiprocessing
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import config
import pytest

from core.db.connect import clickhouse


class _FakeManager:
    def __init__(self, options, *, fail_on_clear=False):
        self.options = options
        self.fail_on_clear = fail_on_clear
        self.clear_calls = 0

    def clear(self):
        self.clear_calls += 1
        if self.fail_on_clear:
            raise RuntimeError("clear failed")


@pytest.fixture(autouse=True)
def _isolated_pool_registry(monkeypatch):
    clickhouse.close_clickhouse_pool_managers()
    clickhouse._registry.current = clickhouse._PoolManagerRegistry(
        pid=os.getpid(),
        lock=threading.Lock(),
        managers={},
    )
    clickhouse._registry.reset_lock = threading.Lock()

    for name in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "no_proxy", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)

    yield

    clickhouse.close_clickhouse_pool_managers()
    clickhouse._registry.current = clickhouse._PoolManagerRegistry(
        pid=os.getpid(),
        lock=threading.Lock(),
        managers={},
    )
    clickhouse._registry.reset_lock = threading.Lock()


@pytest.fixture
def client_factory_spy(monkeypatch):
    managers = []
    clients = []

    def get_pool_manager(**options):
        manager = _FakeManager(options)
        managers.append(manager)
        return manager

    def get_client(**kwargs):
        client = SimpleNamespace(kwargs=kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(clickhouse.httputil, "get_pool_manager", get_pool_manager)
    monkeypatch.setattr(clickhouse.clickhouse_connect, "get_client", get_client)
    return managers, clients


def test_reuses_one_manager_for_many_clients_and_hosts(monkeypatch, client_factory_spy):
    managers, clients = client_factory_spy
    monkeypatch.setenv("CLICKHOUSE_HTTP_POOL_MAXSIZE", "8")
    original_kwargs = {
        "host": "clickhouse-a.internal",
        "port": 8123,
        "username": "first-user",
        "database": "first-db",
        "interface": "http",
    }

    created = []
    for index in range(300):
        kwargs = {
            **original_kwargs,
            "host": f"clickhouse-{index % 3}.internal",
            "username": f"user-{index}",
            "database": f"db-{index}",
            "settings": {"max_threads": index + 1},
        }
        created.append(clickhouse.create_clickhouse_client(kwargs))

    assert len(managers) == 1
    assert len(clients) == 300
    assert len({id(client) for client in created}) == 300
    assert {client.kwargs["pool_mgr"] for client in clients} == {managers[0]}
    assert "pool_mgr" not in original_kwargs
    assert managers[0].options["maxsize"] == 8
    assert managers[0].options["block"] is True


def test_concurrent_client_creation_creates_one_manager(client_factory_spy):
    managers, clients = client_factory_spy
    kwargs = {"host": "clickhouse.internal", "port": 8123, "interface": "http"}

    with ThreadPoolExecutor(max_workers=32) as executor:
        created = list(executor.map(lambda _: clickhouse.create_clickhouse_client(kwargs), range(32)))

    assert len(managers) == 1
    assert len(clients) == 32
    assert len({id(client) for client in created}) == 32
    assert {client.kwargs["pool_mgr"] for client in clients} == {managers[0]}


def test_client_initialisation_happens_outside_registry_lock(monkeypatch):
    monkeypatch.setattr(
        clickhouse.httputil,
        "get_pool_manager",
        lambda **options: _FakeManager(options),
    )

    def get_client(**kwargs):
        registry_lock = clickhouse._registry.current.lock
        assert registry_lock.acquire(blocking=False)
        registry_lock.release()
        return SimpleNamespace(kwargs=kwargs)

    monkeypatch.setattr(clickhouse.clickhouse_connect, "get_client", get_client)

    clickhouse.create_clickhouse_client(
        {"host": "clickhouse.internal", "port": 8123, "interface": "http"}
    )


def test_tls_transport_options_split_managers(client_factory_spy):
    managers, _ = client_factory_spy
    base = {"host": "clickhouse.internal", "port": 8443, "interface": "https"}

    clickhouse.create_clickhouse_client(base)
    clickhouse.create_clickhouse_client({**base, "verify": False})
    clickhouse.create_clickhouse_client({**base, "ca_cert": "first-ca.pem"})
    clickhouse.create_clickhouse_client({**base, "client_cert": "client.pem"})
    clickhouse.create_clickhouse_client({**base, "client_cert_key": "client.key"})
    clickhouse.create_clickhouse_client({**base, "server_host_name": "db.example.test"})
    clickhouse.create_clickhouse_client({**base, "server_host_name": "DB.EXAMPLE.TEST"})

    assert len(managers) == 6
    server_name_options = managers[-1].options
    assert server_name_options["assert_hostname"] == "db.example.test"
    assert server_name_options["server_hostname"] == "db.example.test"


def test_proxy_selection_honours_environment_and_no_proxy(monkeypatch, client_factory_spy):
    managers, _ = client_factory_spy
    monkeypatch.setenv("HTTPS_PROXY", "proxy.internal:8443")
    monkeypatch.setenv("NO_PROXY", "direct.internal")
    base = {"port": 8443, "interface": "https"}

    clickhouse.create_clickhouse_client({**base, "host": "direct.internal"})
    clickhouse.create_clickhouse_client({**base, "host": "proxied.internal"})

    assert len(managers) == 2
    assert "https_proxy" not in managers[0].options
    assert managers[1].options["https_proxy"] == "https://proxy.internal:8443"


def test_explicit_proxy_overrides_environment_lookup(monkeypatch, client_factory_spy):
    managers, _ = client_factory_spy
    monkeypatch.setenv("HTTPS_PROXY", "environment-proxy:8443")
    monkeypatch.setenv("NO_PROXY", "*")

    clickhouse.create_clickhouse_client(
        {
            "host": "clickhouse.internal",
            "port": 8443,
            "interface": "https",
            "https_proxy": "explicit-proxy:9443",
        }
    )
    clickhouse.create_clickhouse_client(
        {
            "host": "clickhouse.internal",
            "port": 8123,
            "interface": "http",
            "http_proxy": "http://explicit-proxy:8080",
        }
    )

    assert managers[0].options["https_proxy"] == "https://explicit-proxy:9443"
    assert managers[1].options["http_proxy"] == "http://explicit-proxy:8080"


def test_https_http_proxy_fallback_matches_clickhouse_connect(monkeypatch, client_factory_spy):
    managers, _ = client_factory_spy
    monkeypatch.setenv("HTTP_PROXY", "http-fallback.internal:8080")
    base = {"host": "clickhouse.internal", "port": 8443, "interface": "https"}

    clickhouse.create_clickhouse_client(base)
    clickhouse.create_clickhouse_client({**base, "verify": False})

    assert managers[0].options["http_proxy"] == "http://http-fallback.internal:8080"
    assert "http_proxy" not in managers[1].options
    assert managers[1].options["verify"] is False


def test_pid_change_discards_inherited_registry_without_reusing_manager(
    monkeypatch,
    client_factory_spy,
):
    managers, clients = client_factory_spy
    pid = [100]
    monkeypatch.setattr(clickhouse.os, "getpid", lambda: pid[0])
    kwargs = {"host": "clickhouse.internal", "port": 8123, "interface": "http"}

    clickhouse.create_clickhouse_client(kwargs)
    clickhouse.create_clickhouse_client(kwargs)
    inherited_manager = clients[-1].kwargs["pool_mgr"]
    inherited_registry = clickhouse._registry.current
    clickhouse.httputil.all_managers[inherited_manager] = 0

    pid[0] = 101
    clickhouse.create_clickhouse_client(kwargs)

    assert len(managers) == 2
    assert inherited_manager.clear_calls == 0
    assert inherited_manager not in clickhouse.httputil.all_managers
    assert clients[-1].kwargs["pool_mgr"] is not inherited_manager
    assert clickhouse._registry.current is not inherited_registry
    assert clickhouse._registry.current.pid == 101
    assert len(clickhouse._registry.current.managers) == 1


def test_concurrent_pid_fallback_publishes_one_child_registry(monkeypatch, client_factory_spy):
    managers, clients = client_factory_spy
    pid = [100]
    monkeypatch.setattr(clickhouse.os, "getpid", lambda: pid[0])
    kwargs = {"host": "clickhouse.internal", "port": 8123, "interface": "http"}

    clickhouse.create_clickhouse_client(kwargs)
    parent_manager = clients[-1].kwargs["pool_mgr"]
    pid[0] = 101

    with ThreadPoolExecutor(max_workers=32) as executor:
        created = list(executor.map(lambda _: clickhouse.create_clickhouse_client(kwargs), range(32)))

    child_managers = {client.kwargs["pool_mgr"] for client in created}
    assert len(managers) == 2
    assert len(child_managers) == 1
    assert parent_manager not in child_managers
    assert clickhouse._registry.current.pid == 101


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork")
def test_real_fork_starts_with_fresh_registry(client_factory_spy):
    _, clients = client_factory_spy
    kwargs = {"host": "clickhouse.internal", "port": 8123, "interface": "http"}
    clickhouse.create_clickhouse_client(kwargs)
    parent_manager = clients[-1].kwargs["pool_mgr"]
    clickhouse.httputil.all_managers[parent_manager] = 0

    def child_probe() -> None:
        child_client = clickhouse.create_clickhouse_client(kwargs)
        assert child_client.kwargs["pool_mgr"] is not parent_manager
        assert clickhouse._registry.current.pid == os.getpid()
        assert len(clickhouse._registry.current.managers) == 1
        assert parent_manager not in clickhouse.httputil.all_managers
        assert parent_manager.clear_calls == 0

    process = multiprocessing.get_context("fork").Process(target=child_probe)
    process.start()
    process.join(10)
    if process.is_alive():
        process.terminate()
        process.join(5)
        pytest.fail("forked registry probe timed out")

    assert process.exitcode == 0
    assert parent_manager in clickhouse.httputil.all_managers


def test_failed_client_creation_reuses_existing_manager(monkeypatch):
    managers = []

    def get_pool_manager(**options):
        manager = _FakeManager(options)
        managers.append(manager)
        return manager

    monkeypatch.setattr(clickhouse.httputil, "get_pool_manager", get_pool_manager)

    def unavailable_client(**_kwargs):
        raise ConnectionError("unavailable")

    monkeypatch.setattr(clickhouse.clickhouse_connect, "get_client", unavailable_client)
    kwargs = {"host": "clickhouse.internal", "port": 8123, "interface": "http"}

    for _ in range(3):
        with pytest.raises(ConnectionError, match="unavailable"):
            clickhouse.create_clickhouse_client(kwargs)

    assert len(managers) == 1


def test_cleanup_is_idempotent_and_only_removes_owned_managers(monkeypatch):
    managers = []

    def get_pool_manager(**options):
        manager = _FakeManager(options, fail_on_clear=len(managers) == 0)
        managers.append(manager)
        clickhouse.httputil.all_managers[manager] = 0
        return manager

    def get_client(**kwargs):
        return SimpleNamespace(kwargs=kwargs)

    monkeypatch.setattr(clickhouse.httputil, "get_pool_manager", get_pool_manager)
    monkeypatch.setattr(clickhouse.clickhouse_connect, "get_client", get_client)
    foreign_manager = _FakeManager({})
    clickhouse.httputil.all_managers[foreign_manager] = 0

    try:
        clickhouse.create_clickhouse_client(
            {"host": "plain.internal", "port": 8123, "interface": "http"}
        )
        clickhouse.create_clickhouse_client(
            {"host": "secure.internal", "port": 8443, "interface": "https"}
        )

        clickhouse.close_clickhouse_pool_managers()
        clickhouse.close_clickhouse_pool_managers()

        assert [manager.clear_calls for manager in managers] == [1, 1]
        assert all(manager not in clickhouse.httputil.all_managers for manager in managers)
        assert foreign_manager in clickhouse.httputil.all_managers
        assert foreign_manager.clear_calls == 0
    finally:
        clickhouse.httputil.all_managers.pop(foreign_manager, None)


def test_rejects_caller_owned_pool_manager(client_factory_spy):
    managers, clients = client_factory_spy

    with pytest.raises(ValueError, match="pool_mgr is managed by DVT"):
        clickhouse.create_clickhouse_client({"pool_mgr": object()})
    with pytest.raises(ValueError, match="must not be supplied in generic_args"):
        clickhouse.create_clickhouse_client({"generic_args": {"pool_mgr": object()}})
    with pytest.raises(ValueError, match="must not be supplied in the DSN"):
        clickhouse.create_clickhouse_client(
            {"dsn": "http://clickhouse.internal:8123/default?pool_mgr=foreign"}
        )

    assert managers == []
    assert clients == []


def test_generic_transport_arguments_use_driver_precedence(client_factory_spy):
    managers, _ = client_factory_spy

    clickhouse.create_clickhouse_client(
        {
            "host": "clickhouse.internal",
            "port": 8443,
            "interface": "https",
            "verify": True,
            "https_proxy": "top-level-proxy:8443",
            "generic_args": {
                "verify": False,
                "https_proxy": "generic-proxy:9443",
            },
        }
    )

    assert managers[0].options["verify"] is False
    assert managers[0].options["https_proxy"] == "https://generic-proxy:9443"


def test_pool_size_configuration_defaults_to_eight(monkeypatch):
    monkeypatch.delenv("CLICKHOUSE_HTTP_POOL_MAXSIZE", raising=False)

    assert config._get_positive_int_env("CLICKHOUSE_HTTP_POOL_MAXSIZE", 8) == 8


@pytest.mark.parametrize("value", ["0", "-1"])
def test_pool_size_configuration_must_be_positive(monkeypatch, value):
    monkeypatch.setenv("CLICKHOUSE_HTTP_POOL_MAXSIZE", value)

    with pytest.raises(ValueError, match="must be a positive integer"):
        config._get_positive_int_env("CLICKHOUSE_HTTP_POOL_MAXSIZE", 8)
