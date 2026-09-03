from typing import AsyncGenerator

from src.managers.worker_id_manager import WorkerIDManager


async def get_worker_id_manager() -> AsyncGenerator[WorkerIDManager, None]:
    yield WorkerIDManager()
