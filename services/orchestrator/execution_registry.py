import asyncio
from dataclasses import dataclass


@dataclass
class TaskExecutionRecord:
    task_id: str
    worker_id: str
    hostname: str
    pid: int
    rss_bytes: int
    memory_limit_bytes: int | None
    system_ram_used_percent: float
    timestamp: float

    def is_stale(self, now_ts: float, stale_timeout_sec: float) -> bool:
        return (now_ts - self.timestamp) >= stale_timeout_sec


class TaskExecutionRegistry:
    def __init__(self) -> None:
        self._executions: dict[str, TaskExecutionRecord] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, record: TaskExecutionRecord) -> TaskExecutionRecord:
        async with self._lock:
            self._executions[record.task_id] = record
            return record

    async def get(self, task_id: str) -> TaskExecutionRecord | None:
        async with self._lock:
            return self._executions.get(task_id)

    async def remove(self, task_id: str) -> TaskExecutionRecord | None:
        async with self._lock:
            return self._executions.pop(task_id, None)

    async def all(self) -> list[TaskExecutionRecord]:
        async with self._lock:
            return list(self._executions.values())

    async def get_stale(self, now_ts: float, stale_timeout_sec: float) -> list[TaskExecutionRecord]:
        async with self._lock:
            return [
                record
                for record in self._executions.values()
                if record.is_stale(now_ts, stale_timeout_sec)
            ]
