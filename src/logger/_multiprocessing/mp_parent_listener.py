import queue as q
import threading
import time
from datetime import datetime

from loguru import logger as loguru_logger

from .mp_bridge import MP_LOG_BRIDGE_EXTRA_KEY

_VALID_LEVELS = {
    "TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"
}


def _normalize_level(level_val) -> str:
    """
    Приводим уровень к тому, что понимает loguru.logger.log(<LEVEL>, ...).
    Принимает строку или число. По умолчанию -> INFO.
    """
    if level_val is None:
        return "INFO"

    if isinstance(level_val, int):
        return "INFO"

    try:
        s = str(level_val).strip().upper()
    except Exception:
        return "INFO"

    if s in _VALID_LEVELS:
        return s

    if s == "SUCCESS":  # опечатка
        return "SUCCESS"

    return "INFO"


def start_mp_log_listener(
    log_queue,
    stop_flag_callable,
    drain_timeout: float = 1.0,
    payload_handler=None,
):
    def _emit(payload):
        extra = payload.get("extra") or {}
        tb_text = extra.get("traceback_str") or payload.get("exception_text") or payload.get("exception")
        extra = {**extra, MP_LOG_BRIDGE_EXTRA_KEY: True}
        if tb_text:
            extra["traceback_str"] = tb_text

        level_name = _normalize_level(payload.get("level"))
        msg = payload.get("message", "")

        def _patch(record):
            record["name"] = payload.get("name") or record["name"]
            record["module"] = payload.get("module") or record["module"]
            record["function"] = payload.get("function") or record["function"]
            record["line"] = payload.get("line") or record["line"]
            time_iso = payload.get("time_iso")
            if time_iso:
                try:
                    source_time = datetime.fromisoformat(time_iso)
                    current_time = record.get("time")
                    if current_time is None:
                        record["time"] = source_time
                    else:
                        target_tz = source_time.tzinfo or current_time.tzinfo
                        record["time"] = type(current_time).fromtimestamp(
                            source_time.timestamp(),
                            tz=target_tz,
                        )
                except Exception:
                    pass

        loguru_logger.bind(**extra).patch(_patch).log(level_name, msg)
        if payload_handler is not None:
            try:
                payload_handler(payload)
            except Exception as exc:
                print(f"[mp-parent-listener] payload handler failed: {exc}", flush=True)

    def _worker():
        last_emit = time.monotonic()

        while True:
            try:
                payload = log_queue.get(timeout=0.2)

            except Exception:
                payload = None

            if payload is not None:
                try:
                    _emit(payload)
                    last_emit = time.monotonic()
                except Exception as e:
                    print(f"[mp-parent-listener] emit failed: {e}", flush=True)
            else:
                if stop_flag_callable():
                    if (time.monotonic() - last_emit) >= drain_timeout:
                        try:
                            while True:
                                payload = log_queue.get_nowait()
                                _emit(payload)

                        except q.Empty:
                            break

                        except Exception as e:
                            print(f"[mp-parent-listener] final-drain failed: {e}", flush=True)
                            break

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t
