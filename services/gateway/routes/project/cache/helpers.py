from dataclasses import dataclass

from src.db.session import AsyncSession
from src.infra.task import enqueue_task_from_project
from src.modules.pipeline_cache import PipelineCacheFacade
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.domain.types import TaskSource
from src.modules.user.infra.db_models import UserRecord
from src.pipeline.execution_mode import PipelineExecutionMode


@dataclass
class ClearDataCacheResult:
    cleared_keys: list[str]


async def clear_data_cache(
    project: ProjectRecord,
    pipeline_cache: PipelineCacheFacade,
    node_ids: list[str] | None = None,
) -> ClearDataCacheResult:
    result = await pipeline_cache.clear_data_cache(
        project_id=project.id,
        node_ids=node_ids,
    )
    return ClearDataCacheResult(cleared_keys=result.cleared_keys)


@dataclass
class ClearMetadataCacheResult:
    cleared_keys: list[str]
    task_id: str | None = None


async def clear_metadata_cache(
    session: AsyncSession,
    user: UserRecord,
    project: ProjectRecord,
    pipeline_cache: PipelineCacheFacade,
    node_ids: list[str] | None = None,
    send_metadata_task: bool = True,
) -> ClearMetadataCacheResult:
    result = await pipeline_cache.clear_metadata_cache(
        project_id=project.id,
        node_ids=node_ids,
        send_metadata_task=False,
    )

    task_id: str | None = None
    if send_metadata_task:
        task = await enqueue_task_from_project(
            project=project,
            mode=PipelineExecutionMode.METADATA_ONLY,
            force_exec=True,
            user=user,
            session=session,
            source=TaskSource.UI,
        )
        task_id = task.task_id

    return ClearMetadataCacheResult(
        cleared_keys=result.cleared_keys,
        task_id=task_id,
    )
