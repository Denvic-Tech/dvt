from typing import Sequence, Protocol

from ..domain.entities import (
    DCCConnector, 
    DCCProject, 
    DCCTask, 
    DCCTaskLog
)
from ..domain.types import TaskStatus


class DCCGatewayProtocol(Protocol):
    async def ping(self) -> bool:
        ...

    async def get_tasks(
        self,
        connector_id: str,
        limit: int = 100,
        offset: int = 0,
        project_id: str | None = None,
        include_empty_status: bool = True,
    ) -> Sequence[DCCTask]:
        ...

    async def poll_task(
        self,
        connector_id: str,
        timeout: int,
    ) -> DCCTask | None:
        ...

    async def update_task_status(
        self,
        task_id: str,
        connector_id: str,
        status: TaskStatus,
        status_info: str | None = None,
    ) -> DCCTask:
        ...
    
    async def register_connector(self, connector: DCCConnector) -> DCCConnector:
        ...

    async def get_connector(self, connector_id: str) -> DCCConnector | None:
        ...

    async def register_project(self, project: DCCProject) -> DCCProject:
        ...

    async def get_projects(
        self,
        connector_id: str,
        project_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[DCCProject]:
        ...

    async def add_logs(self, logs: list[dict]) -> None:
        ...
