from collections import deque
from typing import List

import config


class MemoryLogSink:
    def __init__(self, max_lines: int = 10_000):
        self.logs = deque(maxlen=max_lines)

    def write(self, message: str):
        self.logs.append(message.strip())

    def flush(self): pass

    def get_logs_list(self) -> List[str]:
        return list(self.logs)


log_memory_buffer = MemoryLogSink(config.LOGGING.MAX_MEMORY_LOGS)


def get_logs_list() -> List[str]:
    return log_memory_buffer.get_logs_list()
