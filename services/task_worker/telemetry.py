import os
import asyncio
import socket
from pathlib import Path

import psutil

from src.logger import logger
from src.schemas.internal import TaskInternal
from services.task_worker.deps.pipeline_callbacks import send_task_execution_telemetry

import config


_CGROUP_V2_MEMORY_MAX = Path("/sys/fs/cgroup/memory.max")
_CGROUP_V1_MEMORY_LIMIT = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
_CGROUP_UNLIMITED_THRESHOLD = 1 << 60


def _read_cgroup_memory_limit(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if not raw or raw == "max":
        return None

    try:
        value = int(raw)
    except ValueError:
        return None

    if value <= 0 or value >= _CGROUP_UNLIMITED_THRESHOLD:
        return None

    return value


def get_effective_memory_limit_bytes() -> int:
    host_total = psutil.virtual_memory().total

    for path in (_CGROUP_V2_MEMORY_MAX, _CGROUP_V1_MEMORY_LIMIT):
        limit = _read_cgroup_memory_limit(path)
        if limit is not None:
            return min(limit, host_total)

    return host_total


async def send_task_telemetry(task: TaskInternal) -> None:
    process = psutil.Process(os.getpid())
    await send_task_execution_telemetry(
        task,
        hostname=socket.gethostname(),
        pid=process.pid,
        rss_bytes=process.memory_info().rss,
        memory_limit_bytes=get_effective_memory_limit_bytes(),
        system_ram_used_percent=psutil.virtual_memory().percent,
    )


async def run_task_telemetry_loop(task: TaskInternal) -> None:
    while True:
        try:
            await send_task_telemetry(task)
        except Exception:
            logger.exception("Failed to publish task execution telemetry", task_id=task.task_id)
        await asyncio.sleep(config.TASK_WORKER.TASK_EXECUTION_TELEMETRY_INTERVAL_SEC)

