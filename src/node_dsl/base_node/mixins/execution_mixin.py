from src import utils
from src.node_dsl.execution_settings import ExecutionSettings
from src.node_dsl.hooks import HookStage
from src.node_dsl.registry import hooks as hooks_registry
from src.pipeline.execution_mode import PipelineExecutionMode

from .base import BaseNodeMixin


class ExecutionNodeMixin(BaseNodeMixin):

    def __init__(
            self,
            *args,
            execution_mode: PipelineExecutionMode,
            execution_settings: ExecutionSettings | None = None,
            **kwargs
    ):
        super().__init__(*args, **kwargs)

        self.execution_mode = execution_mode
        self.execution_settings = execution_settings or ExecutionSettings()

    async def execute(self, mode: PipelineExecutionMode) -> None:
        if mode == PipelineExecutionMode.FULL:
            mode = None  # Чтобы получить все хуки

        if self._process_start_cb:
            await utils.async_run_callable(
                self._process_start_cb,
                user_id=self._user_id,
                project_id=self._project_id,
                task_id=self._task_id,
                node=self
            )

        await hooks_registry.run_async(
            node=self,
            stage=HookStage.BEFORE_PROCESS,
            exec_mode=mode
        )

        if mode == PipelineExecutionMode.METADATA_ONLY:
            await utils.async_run_callable(self.process_metadata, offload_sync=False)
        else:
            await utils.async_run_callable(self.process)
        self._refresh_output_variables()

        await hooks_registry.run_async(
            node=self,
            stage=HookStage.AFTER_PROCESS,
            exec_mode=mode
        )

        if self._process_success_cb:
            await utils.async_run_callable(
                self._process_success_cb,
                user_id=self._user_id,
                project_id=self._project_id,
                task_id=self._task_id,
                node=self
            )

        self.progress_step()
