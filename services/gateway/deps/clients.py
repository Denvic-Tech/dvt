from typing import AsyncGenerator, Any

from aiohttp import ClientSession

import config
from src.clients.scheduler_client import SchedulerClient
from src.clients.orchestrator_client import GrpcOrchestratorClient
from src.runtime.async_runtime import shared_orchestrator


async def get_scheduler_client() -> AsyncGenerator[SchedulerClient, Any]:
    async with ClientSession(base_url=f"http://{config.PROJECT_SCHEDULER.PROJECT_SCHEDULER_HOST}:{config.PROJECT_SCHEDULER.PROJECT_SCHEDULER_PORT}") as session:
        yield SchedulerClient(
            scheduler_url=config.PROJECT_SCHEDULER.PROJECT_SCHEDULER_URL,
            session=session
        )


async def get_orchestrator_client() -> AsyncGenerator[GrpcOrchestratorClient, Any]:
    yield await shared_orchestrator.get()
