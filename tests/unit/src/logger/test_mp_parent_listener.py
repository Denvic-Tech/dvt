from __future__ import annotations

import queue
import threading
import time

from loguru import logger as loguru_logger

from src.logger._multiprocessing.mp_bridge import MP_LOG_BRIDGE_EXTRA_KEY
from src.logger._multiprocessing.mp_parent_listener import start_mp_log_listener
from src.logger.logger import _console_sink_filter


def test_console_sink_filters_records_reemitted_by_mp_bridge() -> None:
    assert _console_sink_filter({"extra": {}}) is True
    assert _console_sink_filter({"extra": {MP_LOG_BRIDGE_EXTRA_KEY: True}}) is False


def test_mp_parent_listener_marks_bridged_record_and_preserves_loguru_time_format() -> None:
    log_queue: queue.Queue = queue.Queue()
    stop_event = threading.Event()
    captured: list[str] = []
    handler_id = loguru_logger.add(
        captured.append,
        format=f"{{time:YYYY-MM-DD HH:mm:ss.SSS}}|{{extra[{MP_LOG_BRIDGE_EXTRA_KEY}]}}|{{message}}",
        filter=lambda record: bool(record["extra"].get(MP_LOG_BRIDGE_EXTRA_KEY)),
        enqueue=False,
    )

    listener = start_mp_log_listener(
        log_queue,
        stop_flag_callable=stop_event.is_set,
        drain_timeout=0.01,
    )
    try:
        log_queue.put(
            {
                "time_iso": "2026-08-19T14:53:10.409+00:00",
                "level": "DEBUG",
                "message": "TimeSleepNode received: first, sleep time: 2",
                "name": "src.nodes.testing.time_sleep",
                "module": "time_sleep",
                "function": "process",
                "line": 22,
                "extra": {},
            }
        )

        deadline = time.monotonic() + 1.0
        while not captured and time.monotonic() < deadline:
            time.sleep(0.01)

        assert captured == [
            "2026-08-19 14:53:10.409|True|TimeSleepNode received: first, sleep time: 2\n"
        ]
    finally:
        stop_event.set()
        listener.join(timeout=1.0)
        loguru_logger.remove(handler_id)

    assert listener.is_alive() is False
