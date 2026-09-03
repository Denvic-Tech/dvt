from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, Mock

import pytest

import config
from src.managers.worker_id_manager import WorkerIDManager


@pytest.mark.asyncio
async def test_get_hwid_returns_existing_file_without_regenerating(monkeypatch, tmp_path):
    monkeypatch.setattr(config.PROJECT, "HWID_PATH", tmp_path)
    (tmp_path / "hwid.id").write_text("existing-hwid")

    generator_mock = Mock(return_value="generated-hwid")
    monkeypatch.setattr(
        WorkerIDManager,
        "_load_shared_hwid_generator",
        staticmethod(lambda: generator_mock),
    )

    manager = WorkerIDManager()

    hwid = await manager.get_hwid()

    assert hwid == "existing-hwid"
    generator_mock.assert_not_called()


@pytest.mark.asyncio
async def test_get_hwid_generates_and_persists_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config.PROJECT, "HWID_PATH", tmp_path)
    monkeypatch.setattr(
        WorkerIDManager,
        "_load_shared_hwid_generator",
        staticmethod(lambda: (lambda: "generated-hwid")),
    )

    manager = WorkerIDManager()

    hwid = await manager.get_hwid()

    assert hwid == "generated-hwid"
    assert (tmp_path / "hwid.id").read_text() == "generated-hwid"


@pytest.mark.asyncio
async def test_get_hwid_regenerates_when_file_is_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(config.PROJECT, "HWID_PATH", tmp_path)
    (tmp_path / "hwid.id").write_text(" \n")
    monkeypatch.setattr(
        WorkerIDManager,
        "_load_shared_hwid_generator",
        staticmethod(lambda: (lambda: "regenerated-hwid")),
    )

    manager = WorkerIDManager()

    hwid = await manager.get_hwid()

    assert hwid == "regenerated-hwid"
    assert (tmp_path / "hwid.id").read_text() == "regenerated-hwid"


@pytest.mark.asyncio
async def test_get_hwid_falls_back_to_machine_id_when_shared_generator_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(config.PROJECT, "HWID_PATH", tmp_path)
    monkeypatch.setattr(
        WorkerIDManager,
        "_load_shared_hwid_generator",
        staticmethod(lambda: (lambda: (_ for _ in ()).throw(RuntimeError("generator failed")))),
    )
    monkeypatch.setattr("src.managers.worker_id_manager.platform.system", lambda: "Linux")
    monkeypatch.setattr(
        WorkerIDManager,
        "get_linux_machine_id",
        AsyncMock(return_value="linux-machine-id"),
    )

    manager = WorkerIDManager()

    hwid = await manager.get_hwid()

    assert hwid == hashlib.sha256(b"linux-machine-id").hexdigest()
    assert (tmp_path / "hwid.id").read_text() == hwid


@pytest.mark.asyncio
async def test_get_hwid_in_docker_uses_generation_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config.PROJECT, "HWID_PATH", tmp_path)
    monkeypatch.setattr(
        WorkerIDManager,
        "_load_shared_hwid_generator",
        staticmethod(lambda: (lambda: "docker-hwid")),
    )
    monkeypatch.setattr(WorkerIDManager, "_running_in_docker", staticmethod(lambda: True))

    manager = WorkerIDManager()

    hwid = await manager.get_hwid()

    assert hwid == "docker-hwid"
    assert (tmp_path / "hwid.id").read_text() == "docker-hwid"


@pytest.mark.asyncio
async def test_get_hwid_falls_back_to_uuid_when_machine_id_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(config.PROJECT, "HWID_PATH", tmp_path)
    monkeypatch.setattr(
        WorkerIDManager,
        "_load_shared_hwid_generator",
        staticmethod(lambda: (lambda: (_ for _ in ()).throw(RuntimeError("generator failed")))),
    )
    monkeypatch.setattr("src.managers.worker_id_manager.platform.system", lambda: "Linux")
    monkeypatch.setattr(WorkerIDManager, "get_linux_machine_id", AsyncMock(return_value=""))
    monkeypatch.setattr("src.managers.worker_id_manager.uuid.uuid4", lambda: "uuid-fallback")

    manager = WorkerIDManager()

    hwid = await manager.get_hwid()

    assert hwid == hashlib.sha256(b"uuid-fallback").hexdigest()
    assert (tmp_path / "hwid.id").read_text() == hwid
