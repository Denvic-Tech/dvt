from queue import Full
from multiprocessing import Queue

from loguru import logger as loguru_logger

from src.logger.formatters import sink_formatter

from .mp_bridge import reduce_loguru_message


def add_mp_queue_sink_child(log_queue: Queue, level: str = "DEBUG") -> int:
    def _sink(message):
        try:
            rec = reduce_loguru_message(message)
            log_queue.put_nowait(rec.to_dict())

        except Full:

            pass
        except Exception as e:
            print(f"[mp-child-sink] failed to send log: {e}", flush=True)

    return loguru_logger.add(
        _sink,
        level=level.upper(),
        enqueue=False,
        catch=True,
        format=sink_formatter,
    )
