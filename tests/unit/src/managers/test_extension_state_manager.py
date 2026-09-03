from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import sqlalchemy as sa

from src.managers.extension_state_manager import ExtensionStateManager
from src.models.extension import ExtensionRecord


def test_update_state_serializes_parallel_updates(monkeypatch, test_db_engine) -> None:
    extension_name = f"extension-state-{uuid.uuid4()}"

    with test_db_engine.begin() as conn:
        conn.execute(
            sa.insert(ExtensionRecord).values(
                name=extension_name,
                display_name="Extension State Test",
                description="",
                manifest_json={},
                state_json={"bitrix_api_limits": {"counter": 0}},
                is_enabled=True,
                is_installed=True,
            )
        )

    monkeypatch.setattr("src.managers.extension_state_manager.engine", test_db_engine)

    barrier = threading.Barrier(2)

    def increment_counter() -> dict[str, int]:
        barrier.wait(timeout=5)

        def updater(current_state: dict[str, int]) -> dict[str, int]:
            current_counter = current_state.get("counter", 0)
            time.sleep(0.05)
            return {"counter": current_counter + 1}

        return ExtensionStateManager.update_state(
            extension_name=extension_name,
            key="bitrix_api_limits",
            updater=updater,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(increment_counter)
        second = executor.submit(increment_counter)
        first.result(timeout=10)
        second.result(timeout=10)

    with test_db_engine.connect() as conn:
        state_json = conn.execute(
            sa.select(ExtensionRecord.state_json).where(ExtensionRecord.name == extension_name)
        ).scalar_one()

    assert state_json["bitrix_api_limits"] == {"counter": 2}
