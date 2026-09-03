from traceback import print_exc
from typing import List, Optional

from fastapi import APIRouter, Depends

from services.gateway.deps.clients import get_orchestrator_client
from services.gateway.deps.system_info_manager import get_sys_info
from services.gateway.update_runtime import get_system_state_monitor

from src.clients.orchestrator_client import GrpcOrchestratorClient
from src.clients.scheduler_client import SchedulerClient, get_schedule_client
from src.schemas.http.system import (
    RuntimeConfig,
    RuntimeConfigFeatures,
    ServicesStatus,
    SystemInfo,
    SystemStateResponse,
    VersionInfo,
    WorkerSystemInfo,
)
from src.version import get_version_from_pyproject

import config

r = router = APIRouter(
    prefix="/system",
    tags=["System"],
)


@r.get("/stats", response_model=SystemInfo)
async def get_system_info(sys_info: SystemInfo = Depends(get_sys_info)):
    return sys_info


@r.get("/services-stats", response_model=ServicesStatus)
async def get_services_system_info(
        sys_info: SystemInfo = Depends(get_sys_info),
        orchestrator_client: GrpcOrchestratorClient = Depends(get_orchestrator_client),
        schedule_client: SchedulerClient = Depends(get_schedule_client)
):
    scheduler_sys_info: Optional[SystemInfo] = None
    worker_sys_info: Optional[List[WorkerSystemInfo]] = None

    try:
        worker_sys_info = await orchestrator_client.get_system_stats()
    except Exception:
        print_exc()

    try:
        scheduler_sys_info = await schedule_client.system_status()
    except Exception:
        print_exc()

    return ServicesStatus(
        gateway=sys_info,
        project_scheduler=scheduler_sys_info,
        task_workers=worker_sys_info,
    )


@r.get("/version", response_model=VersionInfo)
async def get_version():
    return VersionInfo(version=get_version_from_pyproject())


@r.get("/state", response_model=SystemStateResponse)
async def get_system_state() -> SystemStateResponse:
    snapshot = get_system_state_monitor().snapshot
    return SystemStateResponse(
        state=snapshot.state,
        retry_after_sec=snapshot.retry_after_sec,
        checked_at=snapshot.checked_at,
    )


@r.get("/runtime-config", response_model=RuntimeConfig)
async def get_runtime_config():
    return RuntimeConfig(
        features=RuntimeConfigFeatures(ai_analysis=config.AI_ANALYSIS.ENABLED),
    )
