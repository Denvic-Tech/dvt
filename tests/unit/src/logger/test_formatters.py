import queue
import time

from src.logger._multiprocessing.mp_parent_listener import start_mp_log_listener
from src.logger.formatters import sink_formatter


def test_sink_formatter_preserves_traceback_from_extra(monkeypatch):
    monkeypatch.setattr(
        "src.logger.formatters.format_concise_traceback",
        lambda _record: "must-not-overwrite",
    )
    record = {
        "exception": None,
        "extra": {"traceback_str": "Traceback text from subprocess"},
    }

    sink_formatter(record)

    assert record["extra"]["traceback_str"] == "Traceback text from subprocess"


def test_sink_formatter_sets_none_if_traceback_missing():
    record = {
        "exception": None,
        "extra": {},
    }

    sink_formatter(record)

    assert record["extra"]["traceback_str"] is None


def test_sink_formatter_builds_traceback_for_native_exception(monkeypatch):
    monkeypatch.setattr(
        "src.logger.formatters.format_concise_traceback",
        lambda _record: "generated traceback",
    )
    record = {
        "exception": object(),
        "extra": {},
    }

    sink_formatter(record)

    assert record["extra"]["traceback_str"] == "generated traceback"


def test_mp_parent_listener_re_emits_traceback_via_extra(monkeypatch):
    emitted = []

    class _BoundLogger:
        def __init__(self, extra):
            self._extra = extra
            self._patcher = None

        def patch(self, patcher):
            self._patcher = patcher
            return self

        def log(self, level, message):
            record = {
                "name": "default",
                "module": "default",
                "function": "default",
                "line": 0,
                "time": None,
            }
            if self._patcher is not None:
                self._patcher(record)
            emitted.append(
                {
                    "level": level,
                    "message": message,
                    "extra": self._extra,
                    "record": record,
                }
            )

    class _FakeLogger:
        def bind(self, **extra):
            return _BoundLogger(extra)

    monkeypatch.setattr(
        "src.logger._multiprocessing.mp_parent_listener.loguru_logger",
        _FakeLogger(),
    )

    log_queue = queue.Queue()
    stop_state = {"value": False}
    listener = start_mp_log_listener(
        log_queue,
        stop_flag_callable=lambda: stop_state["value"],
        drain_timeout=0.01,
    )

    log_queue.put(
        {
            "time_iso": "2026-03-16T14:26:41.622000+05:00",
            "level": "ERROR",
            "message": "node failed",
            "name": "src.pipeline.processor",
            "module": "processor",
            "function": "process",
            "line": 430,
            "extra": {
                "task_id": "task-1",
            },
            "exception_text": "Traceback (most recent call last):\nValueError: boom",
        }
    )

    deadline = time.time() + 1.0
    while not emitted and time.time() < deadline:
        time.sleep(0.01)

    stop_state["value"] = True
    listener.join(timeout=1.0)

    assert len(emitted) == 1
    event = emitted[0]
    assert event["level"] == "ERROR"
    assert event["message"] == "node failed"
    assert event["extra"]["task_id"] == "task-1"
    assert "ValueError: boom" in event["extra"]["traceback_str"]
    assert event["record"]["name"] == "src.pipeline.processor"
    assert event["record"]["module"] == "processor"
    assert event["record"]["function"] == "process"
    assert event["record"]["line"] == 430
    assert event["record"]["time"].isoformat() == "2026-03-16T14:26:41.622000+05:00"
