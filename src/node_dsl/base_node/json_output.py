from abc import ABC
from typing import Any

from core.hashing import get_hash

from src import enums, utils
from src.logger import logger
from src.modules.pipeline_cache import (
    DataIndexEntry,
    JSONKey,
)
from src.node_dsl.hooks import HookStage
from src.node_dsl.node_meta import JSONOutputNodeMeta
from src.node_dsl.node_typing import IO
from src.node_dsl.registry import hooks as hooks_registry
from src.pipeline.execution_mode import PipelineExecutionMode

from .base import BaseNode


class JSONOutputBaseNode(BaseNode, ABC, metaclass=JSONOutputNodeMeta):
    """
    Базовый класс для нод, которые имеют JSON в качестве выходного поля.
    """

    TYPE = enums.NodeType.BASE

    output: IO.JSON = None

    @staticmethod
    def _is_json_io_type(value: object) -> bool:
        if isinstance(value, list):
            return any(str(v) == str(IO.JSON) for v in value)
        return str(value) == str(IO.JSON)

    async def _cleanup_old_cache(self) -> None:
        if self.data_index_store is None:
            logger.warning("'data_index_store' not provided, skipping index store cleanup...")
            return

        index_key = JSONKey(
            project_id=self.project_id,
            node_id=self.node_id,
        )
        exists_entries = await self.data_index_store.query(index_key)
        cache_keys = [entry.cache_key for entry in exists_entries]

        await self.data_index_store.remove(index_key)

        if self.data_store is None:
            logger.warning("'data_store' not provided, skipping data store cleanup...")
            return

        if cache_keys:
            await self.data_store.remove(*cache_keys)

    async def _cache_json_output(self, output_name: str, data: Any) -> None:
        if self.data_store is None:
            logger.warning("'data_store' not provided, skipping storage...")
            return

        if self.data_index_store is None:
            logger.warning("'data_index_store' not provided, skipping storage...")
            return

        payload = {
            "obj": data,
            "output_name": output_name,
            "node_name": self.__class__.__name__,
        }
        cache_key = f"json:{get_hash(payload, deep=False).hex()}"

        index_key = JSONKey(
            project_id=self.project_id,
            node_id=self.node_id,
            output_name=output_name,
        )
        index_entry = DataIndexEntry(
            cache_key=cache_key,
            output_name=output_name,
        )

        await self.data_store.put(
            key=cache_key,
            obj=data,
        )
        await self.data_index_store.put(
            index_key=index_key,
            value=index_entry,
        )

    async def execute(self, mode: PipelineExecutionMode) -> None:
        if mode == PipelineExecutionMode.FULL:
            mode = None  # Чтобы получить все хуки

        if self._process_start_cb:
            await utils.async_run_callable(
                self._process_start_cb,
                user_id=self._user_id,
                project_id=self._project_id,
                task_id=self._task_id,
                node=self,
            )

        await hooks_registry.run_async(
            node=self,
            stage=HookStage.BEFORE_PROCESS,
            exec_mode=mode,
        )

        if mode == PipelineExecutionMode.METADATA_ONLY:
            await utils.async_run_callable(self.process_metadata, offload_sync=False)
        else:
            await utils.async_run_callable(self.process)

        # Для JSON-нод кэшируем именно результат выполнения (exec_mode FULL).
        # По аналогии с DFOutputBaseNode: при FULL сначала чистим старый кэш,
        # затем (если store_enabled) сохраняем новый.
        if mode is None:
            await self._cleanup_old_cache()

            if self._store_enabled:
                for field_name, field in self._output_field_instances.items():
                    if not self._is_json_io_type(field.resolved_type):
                        continue

                    value = getattr(self, field.attr_name, None)
                    await self._cache_json_output(field_name, value)

        await hooks_registry.run_async(
            node=self,
            stage=HookStage.AFTER_PROCESS,
            exec_mode=mode,
        )

        if self._process_success_cb:
            await utils.async_run_callable(
                self._process_success_cb,
                user_id=self._user_id,
                project_id=self._project_id,
                task_id=self._task_id,
                node=self,
            )

        self.progress_step()
