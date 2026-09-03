# TODO: вынести в src/integrations/DCC

import asyncio
import threading
from datetime import UTC, datetime
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from src.crud import project as project_crud
from src.crud.admin import user as user_crud
from src.db import async_engine as engine
from src.exception_registry import ProjectNotFoundException
from src.infra.task import enqueue_task_from_project
from src.integrations.DCC import (
    HttpxDCCGateway,
    entities as dcc_entities,
    http as dcc_http,
    types as dcc_types,
)
from src.logger import logger
from src.modules.app_settings import DVTAppSettings, get_app_settings
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.infra.queries import task_exists
from src.pipeline.execution_mode import PipelineExecutionMode

import config


class DCCManager:
    def __init__(self):
        self.dcc_client: dcc_http.DCCHttpClient | None = None
        self.dcc_gateway: HttpxDCCGateway | None = None

        self.auth_hash: str | None = None

        self._stop_event = threading.Event()

    @staticmethod
    async def _sleep(seconds: float):
        """Эквивалент time.sleep(seconds), но прерываемый при shutdown."""
        await asyncio.sleep(max(0.0, float(seconds)))

    @staticmethod
    def _build_auth_hash(dcc_username: str, dcc_password: str) -> str:
        return str(hash(f"{dcc_username}:{dcc_password}"))

    def ensure_client(self, app_config: DVTAppSettings) -> dcc_http.DCCHttpClient:
        current_auth_hash = self._build_auth_hash(
            dcc_username=app_config.dcc.username,
            dcc_password=app_config.dcc.password,
        )

        if self.dcc_client is None or current_auth_hash != self.auth_hash:
            self.dcc_client = dcc_http.DCCHttpClient(
                base_url=app_config.dcc.url,
                auth=dcc_http.build_dcc_auth(
                    username=app_config.dcc.username,
                    password=app_config.dcc.password,
                )
            )
            self.auth_hash = current_auth_hash

        return self.dcc_client

    def ensure_gateway(self, app_config: DVTAppSettings) -> HttpxDCCGateway:
        if self.dcc_gateway is None:
            dcc_client = self.ensure_client(app_config)
            self.dcc_gateway = HttpxDCCGateway(client=dcc_client)
        return self.dcc_gateway

    def request_stop(self):
        self._stop_event.set()

    async def init(self):
        try:
            app_config = await self._wait_for_app_config()
            if not app_config:
                logger.error("DCC configuration is not set. Cannot initialize DCC.")
                return

            dcc_gateway = self.ensure_gateway(app_config)

            async with AsyncSession(engine) as session:
                id_connector = app_config.dcc.connector_id

                connector = await dcc_gateway.get_connector(id_connector)
                if not connector:
                    new_connector = self._create_connector(id_connector)
                    await dcc_gateway.register_connector(new_connector)

                result = (await project_crud.get_projects(session=session))
                projects = result.all()
                if not projects:
                    logger.error("No projects found in the database to initialize projects.")
                    return

                await self._init_projects(
                    app_config=app_config,
                    id_connector=id_connector,
                    projects=list(projects)
                )
                logger.info("DCC initialization completed successfully.")

        except Exception as e:
            logger.exception(f"Error during DCC initialization: {e}")
            raise

    async def listen_for_tasks(self):
        app_config = await self._wait_for_app_config()
        if not app_config:
            logger.error("DCC configuration is not set. Cannot listen for tasks.")
            return

        while not self._stop_event.is_set():
            try:
                await self._listen_task_long_polling(app_config)
            except Exception as e:
                logger.exception(
                    f"Error while listening for tasks, retry in {config.DCC_INTEGRATION.DCC_TASK_LISTEN_INTERVAL} sec: {e}"
                )

    async def _listen_task_long_polling(self, app_config: DVTAppSettings):
        dcc_gateway = self.ensure_gateway(app_config)

        connector = await dcc_gateway.get_connector(app_config.dcc.connector_id)
        if not connector:
            logger.error(f"Connector with ID {app_config.dcc.connector_id} not found in DCC.")
            return

        dcc_task = await dcc_gateway.poll_task(
            connector_id=app_config.dcc.connector_id,
            timeout=5
        )

        if dcc_task is None:
            return

        if dcc_task.status is not None:
            logger.info(f"Task status is {dcc_task.status}, skipping")
            return

        logger.info(f"Received task with id({dcc_task.id_task}) from DCC")

        async with AsyncSession(engine) as session:
            if await task_exists(session, task_id=dcc_task.id_task):
                logger.warning("Task already exists in DB")
                return

            project = (await project_crud.get_projects_by(session, project_id=dcc_task.id_project)).first()

            if not project:
                raise ProjectNotFoundException

            user = await user_crud.get_default_service_user(
                session,
            )

            try:
                await enqueue_task_from_project(
                    project=project,
                    task_id=dcc_task.id_task,
                    mode=PipelineExecutionMode.FULL,
                    force_exec=True,
                    user=user,
                    session=session,
                )
            except Exception as e:
                logger.exception("Failed to push task %s to queue: %s", dcc_task.id_task, e)
                return

            try:
                await dcc_gateway.update_task_status(
                    task_id=dcc_task.id_task,
                    connector_id=app_config.dcc.connector_id,
                    status=dcc_types.TaskStatus.WAITING,
                    status_info="Task is being processed",
                )
            except Exception as e:
                logger.exception("Failed to update DCC task status: %s", e)


    async def _wait_for_app_config(self) -> Optional[DVTAppSettings]:
        try:
            while not self._stop_event.is_set():
                async with AsyncSession(engine) as session:
                    app_config = await get_app_settings(session=session)
                    if all([app_config.dcc.url, app_config.dcc.username, app_config.dcc.password]):
                        gateway = self.ensure_gateway(app_config)
                        if await gateway.ping() and app_config.dcc.connector_id:
                            logger.info("DCC is ready.")
                            return app_config

                await self._sleep(config.DCC_INTEGRATION.DCC_READY_STATUS_CHECK_INTERVAL)

        except Exception as e:
            logger.exception(e)
            return None

    async def _init_projects(
        self,
        app_config: DVTAppSettings,
        id_connector: str,
        projects: list[ProjectRecord],
    ):
        dcc_gateway = self.ensure_gateway(app_config)
        dcc_projects = await dcc_gateway.get_projects(id_connector)
        dcc_project_ids = {p.id_project for p in dcc_projects if p.id_project}

        for project in projects:
            if project.id in dcc_project_ids:
                continue

            project = dcc_entities.DCCProject(
                id_project=project.id,
                id_connector=id_connector,
                name=project.name,
                type="DVT",
            )
            registered = await dcc_gateway.register_project(project)
            logger.info(f"Registered new project: {registered.id_project}")
            await self._sleep(getattr(config, "DCC_PER_PROJECT_SLEEP", 0.2))

        logger.info("All projects are initialized (or already existed).")

    def _create_connector(self, id_connector: str) -> dcc_entities.DCCConnector:
        """
        Создает объект Connector с уникальным ID и текущей меткой времени.
        """
        connector = dcc_entities.DCCConnector(
            id_connector=id_connector,
            type="DVT",
            name="DVT",
            group_name="",
            user_name="",
            timestamp=datetime.now(tz=UTC)
        )
        return connector


dcc_manager: Optional[DCCManager] = None


def get_dcc_manager():
    global dcc_manager

    if dcc_manager is None:
        dcc_manager = DCCManager()
    return dcc_manager


if __name__ == '__main__':
    dcc_manager.listen_for_tasks()
