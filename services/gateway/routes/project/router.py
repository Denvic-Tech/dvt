from fastapi import APIRouter

from .crud import router as crud_router
from .copy import router as copy_router
from .variables import router as variables_router
from .file_inputs import router as file_inputs_router

from services.gateway.routes.project.graph.common import router as graph_common_router
from services.gateway.routes.project.graph.graph_operations import router as graph_operations_router

from .cache import router as cache_router
from .data.dataframe import router as dataframe_router
from .data.json import router as json_router

from .task import router as task_router
from .logs import router as logs_router
from .ai_analysis import router as ai_analysis_router

from .schedule import router as schedule_router

router = APIRouter()

router.include_router(crud_router, prefix="/projects", tags=["Projects"])
router.include_router(copy_router, prefix="/projects", tags=["Projects"])
router.include_router(schedule_router, prefix="/projects", tags=["Project Scheduler"])
router.include_router(task_router, prefix="/projects/{project_id}", tags=["Tasks"])
router.include_router(logs_router, prefix="/projects/{project_id}", tags=["Project Logs"])
router.include_router(ai_analysis_router, prefix="/projects/{project_id}", tags=["AI Analysis"])
router.include_router(variables_router, prefix="/projects/{project_id}/variables", tags=["Projects"])
router.include_router(file_inputs_router, prefix="/projects/{project_id}/graph/nodes", tags=["Project File Inputs"])

router.include_router(
    graph_common_router,
    prefix="/projects/{project_id}/graph",
    tags=["Graph"],
)
router.include_router(
    graph_operations_router,
    prefix="/projects/{project_id}/graph-ops",
    tags=["Graph Operations"],
)

router.include_router(
    dataframe_router,
    prefix="/projects/{project_id}/dataframe",
    tags=["DataFrame"],
)

router.include_router(
    json_router,
    prefix="/projects/{project_id}/json",
    tags=["JSON"],
)

router.include_router(
    cache_router,
    prefix="/projects/{project_id}/cache",
    tags=["Cache"],
)
