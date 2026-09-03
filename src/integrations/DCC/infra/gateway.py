import httpx
from pydantic import ValidationError, TypeAdapter

from ..domain.types import TaskStatus

from src.integrations.DCC.flows.protocols import DCCGatewayProtocol

from .exceptions import (
    DCCTransportError, DCCResponseValidationError, DCCUnexpectedResponseError
)
from src.integrations.DCC.domain.entities import (
    DCCTask,
    DCCProject,
    DCCConnector, DCCTaskLog
)
from .http.client import DCCHttpClient
from .http import endpoints


class HttpxDCCGateway(DCCGatewayProtocol):
    def __init__(self, client: DCCHttpClient) -> None:
        self._client = client

        self._task_list_adapter = TypeAdapter(list[DCCTask])
        self._project_list_adapter = TypeAdapter(list[DCCProject])

    async def ping(self) -> bool:
        try:
            response = await self._client.ping()
            response.raise_for_status()
            return True
        except httpx.HTTPError as e:
            raise DCCTransportError("DCC ping failed") from e

    async def get_tasks(
            self,
            connector_id: str,
            limit: int = 100,
            offset: int = 0,
            project_id: str | None = None,
            include_empty_status: bool = True,
    ) -> list[DCCTask]:
        params = {
            "page_size": limit,
            "offset": offset,
            "id_connector": connector_id,
            "include_empty_status": include_empty_status,
        }
        if project_id:
            params["id_project"] = project_id

        try:
            response = await self._client.get(endpoints.GET_TASKS, params=params)
            response.raise_for_status()
            payload = response.json()
            return self._task_list_adapter.validate_python(payload["data"])

        except httpx.HTTPError as e:
            raise DCCTransportError("Failed to fetch DCC tasks") from e
        except (ValidationError, KeyError, TypeError) as e:
            raise DCCResponseValidationError("Invalid DCC tasks response") from e

    async def poll_task(
            self,
            connector_id: str,
            timeout: int,
    ) -> DCCTask | None:
        params = {"id_connector": connector_id, "timeout": timeout}

        try:
            response = await self._client.get(
                endpoints.GET_TASK_LONG_POLLING,
                params=params,
            )
            response.raise_for_status()

            if not response.text or not response.text.strip():
                return None

            payload = response.json()
            if not isinstance(payload, dict):
                raise DCCUnexpectedResponseError(
                    f"Expected dict payload, got {type(payload)!r}"
                )

            return DCCTask.model_validate(payload)

        except httpx.HTTPError as e:
            raise DCCTransportError("Failed to poll DCC task") from e

        except ValidationError as e:
            raise DCCResponseValidationError("Invalid DCC polled task response") from e

    async def update_task_status(
            self,
            task_id: str,
            connector_id: str,
            status: TaskStatus,
            status_info: str | None = None,
    ) -> DCCTask:
        payload = {
            "id_task": task_id,
            "id_connector": connector_id,
            "status": status.value,
        }
        if status_info is not None:
            payload["status_info"] = status_info

        try:
            response = await self._client.post(
                endpoints.UPDATE_TASK_STATUS,
                json=payload,
            )
            response.raise_for_status()
            return DCCTask.model_validate(response.json())
        except httpx.HTTPError as e:
            raise DCCTransportError("Failed to update DCC task status") from e
        except ValidationError as e:
            raise DCCResponseValidationError("Invalid DCC task response") from e

    async def register_connector(self, connector: DCCConnector) -> DCCConnector:
        payload = {
            "id_connector": connector.id,
            "name": connector.name,
            "source_type": connector.source_type,
        }

        try:
            response = await self._client.post(
                endpoints.REGISTER_CONNECTOR,
                json=payload,
            )
            response.raise_for_status()
            return DCCConnector.model_validate(response.json())
        except httpx.HTTPError as e:
            raise DCCTransportError("Failed to register DCC connector") from e
        except ValidationError as e:
            raise DCCResponseValidationError("Invalid DCC connector response") from e

    async def get_connector(self, connector_id: str) -> DCCConnector | None:
        params = {
            "page_size": 1,
            "offset": 0,
            "id_connector": connector_id,
        }

        try:
            response = await self._client.get(endpoints.GET_CONNECTORS, params=params)
            response.raise_for_status()
            payload = response.json()

            if payload.get("count", 0) == 0:
                return None

            return DCCConnector.model_validate(payload["data"][0])
        except httpx.HTTPError as e:
            raise DCCTransportError("Failed to fetch DCC connector") from e
        except (ValidationError, KeyError, TypeError) as e:
            raise DCCResponseValidationError("Invalid DCC connector response") from e

    async def register_project(self, project: DCCProject) -> DCCProject:
        payload = {
            "id_project": project.id,
            "id_connector": project.connector_id,
            "name": project.name,
        }

        try:
            response = await self._client.post(
                endpoints.REGISTER_PROJECT,
                json=payload,
            )
            response.raise_for_status()
            return DCCProject.model_validate(response.json())
        except httpx.HTTPError as e:
            raise DCCTransportError("Failed to register DCC project") from e
        except ValidationError as e:
            raise DCCResponseValidationError("Invalid DCC project response") from e

    async def get_projects(
            self,
            connector_id: str,
            project_id: str | None = None,
            limit: int = 100,
            offset: int = 0,
    ) -> list[DCCProject]:
        params = {
            "page_size": limit,
            "offset": offset,
            "id_connector": connector_id,
        }
        if project_id:
            params["id_project"] = project_id

        try:
            response = await self._client.get(endpoints.GET_PROJECTS, params=params)
            response.raise_for_status()
            payload = response.json()
            return self._project_list_adapter.validate_python(payload["data"])
        except httpx.HTTPError as e:
            raise DCCTransportError("Failed to fetch DCC projects") from e
        except (ValidationError, KeyError, TypeError) as e:
            raise DCCResponseValidationError("Invalid DCC projects response") from e

    async def add_logs(self, logs: list[DCCTaskLog]) -> None:
        try:
            response = await self._client.post(endpoints.ADD_LOG, json=logs)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise DCCTransportError("Failed to send DCC logs") from e
