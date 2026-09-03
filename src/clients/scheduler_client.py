from typing import Any, AsyncGenerator, List, Optional

import aiohttp
from fastapi import HTTPException

from src.logger import logger
from src.modules.project.infra.http_schemas import ScheduleResponse
from src.schemas.http.system import SystemInfo
from src.schemas.internal import (
    ProjectSchedulePatchRequest,
    ProjectScheduleResponse,
    ProjectScheduleServiceRequest,
)

import config


class SchedulerClient:
    def __init__(
            self,
            scheduler_url: str = config.PROJECT_SCHEDULER.PROJECT_SCHEDULER_URL,
            session: aiohttp.ClientSession | None = None,
    ):
        self._session_owner = session is None
        self.session = session
        self.base_url = scheduler_url

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self.session or self.session.closed:
            # Это условие не должно срабатывать при использовании через async with или корректной передаче сессии
            raise RuntimeError(
                "Session not initialized or closed. Use 'async with SchedulerClient(...)' or provide an active session."
            )

        full_url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        # aiohttp.ClientSession.request принимает полный URL или относительный путь, если base_url был задан при создании сессии.
        # Для ясности и консистентности, если сессия создается клиентом, она будет с base_url.
        # Если сессия передается извне, предполагается, что она либо имеет base_url, либо пути будут абсолютными.
        # Здесь мы используем относительный путь, полагаясь на конфигурацию сессии.
        request_path = f"/{path.lstrip('/')}"

        logger.debug(
            f"SchedulerClient: "
            f"Requesting {method} {full_url} with params {kwargs.get('params') or kwargs.get('json')}"
        )
        try:
            async with self.session.request(method, request_path, **kwargs) as response:
                logger.debug(
                    f"SchedulerClient: Response {method} {full_url} - Status {response.status}"
                )

                response_data: Any
                if response.content_type == "application/json":
                    response_data = await response.json()
                else:
                    # Обработка не-JSON ответов, например, текстовых сообщений об ошибках
                    text_data = await response.text()
                    # Для единообразия создаем словарь, имитирующий структуру ошибки JSON
                    response_data = {"message": text_data, "detail": text_data}

                if not (200 <= response.status < 300):
                    error_message = response_data.get("message", response_data.get("detail", "Unknown scheduler error"))
                    # Если detail сам по себе является словарем (как в BadPipelineException), преобразуем его в строку
                    if isinstance(error_message, dict):
                        error_message = str(error_message)

                    logger.error(
                        f"SchedulerClient: Error {response.status} for {full_url}: {error_message}"
                    )
                    raise HTTPException(
                        status_code=response.status, detail=error_message
                    )
                return response_data
        except aiohttp.ClientConnectionError as e:
            logger.error(f"SchedulerClient: Connection error for {full_url}: {e}")
            raise HTTPException(
                status_code=503, detail=f"Scheduler service unavailable: {e}"
            ) from e
        except aiohttp.ClientError as e:  # Другие ошибки клиента aiohttp
            logger.error(f"SchedulerClient: Client error for {full_url}: {e}")
            raise HTTPException(status_code=500, detail=f"Scheduler client error: {e}")  from e
        except Exception as e:
            logger.exception(f"SchedulerClient: Unexpected error during request to {full_url}")
            raise HTTPException(status_code=500, detail=f"Unexpected scheduler client error: {str(e)}") from e

    async def schedule_project(self, data: dict | ProjectScheduleServiceRequest) -> ScheduleResponse:
        if isinstance(data, ProjectScheduleServiceRequest):
            data = data.model_dump(mode="json", exclude_none=True)
        response_json = await self._request(
            "POST", "/projects/schedule", json=data
        )
        return ScheduleResponse(**response_json)

    async def patch_project_schedule(
        self,
        project_id: str,
        data: dict | ProjectSchedulePatchRequest,
    ) -> ScheduleResponse:
        if isinstance(data, ProjectSchedulePatchRequest):
            data = data.model_dump(mode="json", exclude_unset=True)
        response_json = await self._request(
            "PATCH",
            f"/projects/schedule/{project_id}",
            json=data,
        )
        return ScheduleResponse(**response_json)

    async def delete_project_schedule(self, project_id: str) -> ScheduleResponse:
        response_json = await self._request("DELETE", f"/projects/schedule/{project_id}")
        return ScheduleResponse(**response_json)

    async def unschedule_project(self, project_id: str) -> ScheduleResponse:
        response_json = await self._request("POST", f"/projects/unschedule/{project_id}")
        return ScheduleResponse(**response_json)

    async def get_scheduled_projects(
        self,
        organization_id: str | None = None,
    ) -> List[ProjectScheduleResponse]:
        params = {"organization_id": organization_id} if organization_id is not None else None
        response_json = await self._request("GET", "/projects/scheduled/", params=params)
        return [ProjectScheduleResponse(**project) for project in response_json]

    async def close(self) -> None:
        if self._session_owner and self.session and not self.session.closed:
            await self.session.close()
            logger.debug("SchedulerClient: Owned session closed.")

    async def __aenter__(self) -> "SchedulerClient":
        if self.session is None:
            # Если сессия не была передана, создаем новую.
            # base_url будет использоваться методами session.get(), session.post() и т.д. для формирования полного URL.
            self.session = aiohttp.ClientSession(base_url=self.base_url)
            self._session_owner = True
            logger.debug(f"SchedulerClient: Created new session for {self.base_url}")
        elif self.session.closed:
            raise RuntimeError("SchedulerClient: Provided session is closed.")
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def system_status(self) -> SystemInfo:
        response_json = await self._request("GET", "/system/status")
        return SystemInfo(**response_json)


async def get_schedule_client() -> AsyncGenerator[SchedulerClient, Any]:
    async with aiohttp.ClientSession(base_url=config.PROJECT_SCHEDULER.PROJECT_SCHEDULER_URL) as session:
        yield SchedulerClient(scheduler_url=config.PROJECT_SCHEDULER.PROJECT_SCHEDULER_URL, session=session)
