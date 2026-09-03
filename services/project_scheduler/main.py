import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from loguru import logger
from sqlmodel import Session

from services.project_scheduler.deps import get_project_scheduler_manager
from services.project_scheduler.routes.projects import router as project_router
from services.project_scheduler.routes.stats import router as stats_router
from src.db import engine
from src.managers.dcc_manager import get_dcc_manager
from src.schemas.http.common import CommonResponse
from src.utils.waiting import wait_for_alembic_migrations, wait_for_db

import config


def _wait_for_database_schema() -> None:
    with Session(engine) as session:
        wait_for_db(session)
        wait_for_alembic_migrations(
            session,
            release_path=config.PROJECT.RELEASE_FILE,
            timeout=config.POSTGRES.MIGRATION_WAIT_TIMEOUT_SEC,
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _wait_for_database_schema()

    dcc_manager = get_dcc_manager()

    project_scheduler_manager = get_project_scheduler_manager()
    project_scheduler_manager.start()
    await project_scheduler_manager.init_from_project_schedules()

    # statement = (
    #     select(TaskModel)
    #     .outerjoin(CronModel)
    #     .where(TaskModel.scheduled == True)
    #     .where(CronModel.id.is_not(None))
    # )
    # tasks = session.exec(statement).all()

    # for task in tasks:
    #     logger.debug(f"Scheduling task ID={task.id} NAME={task.name}")
    #     project_scheduler_manager.schedule_task(task=task)

    loop = asyncio.get_running_loop()
    listener_future = asyncio.create_task(dcc_manager.listen_for_tasks())

    try:
        yield
    finally:
        if hasattr(dcc_manager, "request_stop"):
            dcc_manager.request_stop()

        project_scheduler_manager = get_project_scheduler_manager()
        if project_scheduler_manager is not None:
            try:
                await project_scheduler_manager.shutdown()
            except Exception as e:
                logger.exception(f"Error during scheduler shutdown: {e}")


app = FastAPI(
    title="Project Scheduler",
    description="Project Scheduler for B24 Connector",
    version="0.0.1",
    lifespan=lifespan
)


@app.exception_handler(HTTPException)
def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=CommonResponse(
            success=False,
            message=exc.detail
        ).model_dump(),
    )


app.include_router(project_router)
app.include_router(stats_router)
