from __future__ import annotations

from services.task_worker.helpers import async_runner


def test_get_async_runner_reuses_healthy_runner(monkeypatch):
    created = []

    class _FakeRunner:
        def __init__(self):
            self.stop_calls = 0
            created.append(self)

        def is_healthy(self) -> bool:
            return True

        def stop(self) -> None:
            self.stop_calls += 1

    monkeypatch.setattr(async_runner, "AsyncRunner", _FakeRunner)
    monkeypatch.setattr(async_runner.os, "getpid", lambda: 101)
    monkeypatch.setattr(async_runner, "_runner", None)
    monkeypatch.setattr(async_runner, "_runner_pid", None)

    first = async_runner.get_async_runner()
    second = async_runner.get_async_runner()

    assert first is second
    assert len(created) == 1


def test_get_async_runner_recreates_runner_after_fork(monkeypatch):
    created = []
    pid = {"value": 101}

    class _FakeRunner:
        def __init__(self):
            self.stop_calls = 0
            created.append(self)

        def is_healthy(self) -> bool:
            return True

        def stop(self) -> None:
            self.stop_calls += 1

    monkeypatch.setattr(async_runner, "AsyncRunner", _FakeRunner)
    monkeypatch.setattr(async_runner.os, "getpid", lambda: pid["value"])
    monkeypatch.setattr(async_runner, "_runner", None)
    monkeypatch.setattr(async_runner, "_runner_pid", None)

    first = async_runner.get_async_runner()
    pid["value"] = 202
    second = async_runner.get_async_runner()

    assert first is not second
    assert len(created) == 2
    assert first.stop_calls == 0


def test_get_async_runner_recreates_unhealthy_runner(monkeypatch):
    created = []

    class _StaleRunner:
        def __init__(self):
            self.stop_calls = 0

        def is_healthy(self) -> bool:
            return False

        def stop(self) -> None:
            self.stop_calls += 1

    class _FreshRunner:
        def __init__(self):
            created.append(self)

        def is_healthy(self) -> bool:
            return True

        def stop(self) -> None:
            return None

    stale = _StaleRunner()

    monkeypatch.setattr(async_runner, "AsyncRunner", _FreshRunner)
    monkeypatch.setattr(async_runner.os, "getpid", lambda: 101)
    monkeypatch.setattr(async_runner, "_runner", stale)
    monkeypatch.setattr(async_runner, "_runner_pid", 101)

    current = async_runner.get_async_runner()

    assert current is created[0]
    assert stale.stop_calls == 1
