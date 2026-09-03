from fastapi import APIRouter, Depends

from services.project_scheduler.deps import SystemInfo, get_sys_info

r = router = APIRouter(
    prefix="/system",
    tags=["System"],
)


@router.get("/status", response_model=SystemInfo)
async def get_system_info(sys_info: SystemInfo = Depends(get_sys_info)):
    return sys_info
