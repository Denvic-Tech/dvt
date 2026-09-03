import threading
from abc import ABC
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cached_property
from typing import Any

import dask.dataframe as dd
import pandas as pd

from core.hashing import get_hash
from core.types import DataFrameMetadata, DataType

from src import enums, utils
from src.logger import logger
from src.modules.pipeline_cache import IndexStore, MetadataCacheEntry, ObjectStore
from src.modules.pipeline_cache.domain.dataframe_cache import (
    DataFrameCachePolicy,
    DataFrameExecutionOrder,
)
from src.modules.pipeline_cache.domain.fingerprints import create_node_runtime_fingerprint
from src.modules.pipeline_cache.flow.dataframe_execution_cache import DataFrameExecutionCache
from src.modules.pipeline_cache.infra.dask_dataframe_cache import (
    DaskPartitionCacheWriter,
    build_lazy_dataframe,
)
from src.node_dsl.base_node import BaseNode
from src.node_dsl.hooks import HookStage
from src.node_dsl.node_meta import DFOutputNodeMeta
from src.node_dsl.registry import hooks as hooks_registry
from src.node_dsl.types import NodeOutput
from src.pipeline.execution_mode import PipelineExecutionMode
from src.runtime.async_runtime import async_worker


@dataclass(frozen=True)
class DDFOutputMeta:
    attr_name: str
    npartitions: int
    ddf: dd.DataFrame


@dataclass(frozen=True)
class DDFPartitionCallbackContext:
    writer: DaskPartitionCacheWriter | None
    progress_step: Callable[[], None] | None
    progress_lock: threading.Lock


@dataclass
class _NodeCallbacksCoordinator:
    on_started: Callable[[], None]
    on_finished: Callable[[], None]
    _active_operation_ids: set[Any] = field(default_factory=set)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def start_operation(self, operation_id: Any) -> None:
        should_call_started = False
        with self._lock:
            if operation_id not in self._active_operation_ids:
                was_empty = not self._active_operation_ids
                self._active_operation_ids.add(operation_id)
                should_call_started = was_empty
        if should_call_started:
            self.on_started()

    def finish_operation(self, operation_id: Any) -> None:
        should_call_finished = False
        with self._lock:
            if operation_id in self._active_operation_ids:
                self._active_operation_ids.discard(operation_id)
                should_call_finished = not self._active_operation_ids
        if should_call_finished:
            self.on_finished()

    def fail_operation(self, operation_id: Any) -> None:
        with self._lock:
            self._active_operation_ids.discard(operation_id)


def _get_part_no(partition_info: dict[str, Any] | None) -> int | None:
    if not partition_info:
        return None
    part_no = partition_info.get("number")
    return part_no if isinstance(part_no, int) else None



def _on_operation_start(
        _ddf_meta: pd.DataFrame,
        operation_id: Any,
        *,
        callback_coordinator: _NodeCallbacksCoordinator,
        **_: Any,
) -> None:
    callback_coordinator.start_operation(operation_id)


def _on_operation_end(
        _ddf_meta: pd.DataFrame,
        operation_id: Any,
        *,
        callback_coordinator: _NodeCallbacksCoordinator,
        partition_context: DDFPartitionCallbackContext,
        **_: Any,
) -> None:
    if partition_context.writer is not None:
        partition_context.writer.finish()
    callback_coordinator.finish_operation(operation_id)


def _on_operation_error(
        _ddf_meta: pd.DataFrame,
        operation_id: Any,
        _exc: BaseException,
        *,
        callback_coordinator: _NodeCallbacksCoordinator,
        partition_context: DDFPartitionCallbackContext,
        **_: Any,
) -> None:
    if partition_context.writer is not None:
        partition_context.writer.abort()
    callback_coordinator.fail_operation(operation_id)


def _on_operation_partition(
        df_partition: pd.DataFrame,
        _operation_id: Any,
        *,
        partition_context: DDFPartitionCallbackContext,
        partition_info: dict[str, Any] | None = None,
        **_: Any,
) -> None:
    part_no = _get_part_no(partition_info)

    if partition_context.writer is not None and part_no is not None:
        partition_context.writer.submit_partition(df_partition, part_no=part_no)

    if partition_context.progress_step is not None:
        with partition_context.progress_lock:
            partition_context.progress_step()


class DFOutputBaseNode(BaseNode, ABC, metaclass=DFOutputNodeMeta):
    """
    Базовый класс для нод, которые имеют DataFrame в качестве выходного поля.
    Предоставляет удобный интерфейс для работы с DataFrame.
    """

    # --- Атрибуты класса для метаданных ---
    TYPE = enums.NodeType.DATAFRAME_OUTPUT

    # --- Outputs ---
    output: dd.DataFrame = None

    def __init__(self, *args, **kwargs):
        dataframe_cache_policy = kwargs.pop("dataframe_cache_policy", None)
        super().__init__(*args, **kwargs)

        self._dataframe_cache_policy = dataframe_cache_policy or DataFrameCachePolicy()
        self._dataframe_execution_cache: DataFrameExecutionCache | None = None
        self._dataframe_cache_generation_id: str | None = None
        self._dataframe_cache_execution_order = DataFrameExecutionOrder.from_queued_at(
            datetime.now(tz=UTC),
            self.task_id,
        )
        self._dataframe_cache_runtime_fingerprint = create_node_runtime_fingerprint(self.__class__)

    def set_dataframe_cache_execution_order(self, execution_order: DataFrameExecutionOrder) -> None:
        self._dataframe_cache_execution_order = execution_order

    @staticmethod
    def _pandas_dtype_for_metadata(column) -> object:
        dtype_metadata = getattr(column, "dtype_metadata", None)
        dtype_repr = getattr(dtype_metadata, "repr", None)
        if dtype_repr:
            try:
                return pd.api.types.pandas_dtype(dtype_repr)
            except (TypeError, ValueError):
                pass

        mapping = {
            DataType.INT: "Int64",
            DataType.FLOAT: "float64",
            DataType.STRING: "string",
            DataType.BOOLEAN: "boolean",
            DataType.DATETIME: "datetime64[ns]",
            DataType.TIMEDELTA: "timedelta64[ns]",
            DataType.CATEGORY: "category",
            DataType.DICTIONARY: "object",
            DataType.OBJECT: "object",
            DataType.UNKNOWN: "object",
        }
        return mapping.get(column.dtype, "object")

    @classmethod
    def build_empty_pdf_from_metadata(cls, metadata: DataFrameMetadata) -> pd.DataFrame:
        data = {
            column.name: pd.Series(dtype=cls._pandas_dtype_for_metadata(column))
            for column in metadata.columns
            if not column.index
        }
        pdf = pd.DataFrame(data)

        index_columns = [column for column in metadata.columns if column.index]
        if len(index_columns) == 1:
            index_column = index_columns[0]
            pdf.index = pd.Index(
                [],
                dtype=cls._pandas_dtype_for_metadata(index_column),
                name=index_column.name,
            )

        return pdf

    @classmethod
    def build_empty_ddf_from_metadata(
            cls,
            metadata: DataFrameMetadata,
            *,
            npartitions: int = 1,
    ) -> dd.DataFrame:
        pdf = cls.build_empty_pdf_from_metadata(metadata)
        return dd.from_pandas(pdf, npartitions=max(1, npartitions))

    async def _node_started(self):
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
            exec_mode=PipelineExecutionMode.FULL
        )

    async def _node_finished(self):
        await hooks_registry.run_async(
            node=self,
            stage=HookStage.AFTER_PROCESS,
            exec_mode=PipelineExecutionMode.FULL
        )
        if self._process_success_cb:
            await utils.async_run_callable(
                self._process_success_cb,
                user_id=self._user_id,
                project_id=self._project_id,
                task_id=self._task_id,
                node=self
            )

    def _get_input_values(self) -> dict[str, Any]:
        items = self.input_fields().items()
        return {k: getattr(self, k, v.default) for k, v in items}

    @cached_property
    def _hashed_inputs(self) -> dict[str, bytes]:
        return {
            k: get_hash(v, deep=False)
            for k, v in self._get_input_values().items()
        }

    def _execution_cache_ttl(self) -> int | None:
        ttl = getattr(self.project_settings, "ttl_time", None)
        return ttl if isinstance(ttl, int) and ttl > 0 else None

    async def cache_execution_snapshot(
            self,
            *,
            outputs: dict[str, NodeOutput],
            metadata: dict[str, Any],
    ) -> None:
        cache = self._dataframe_execution_cache
        generation_id = self._dataframe_cache_generation_id
        if not self._store_enabled or cache is None or generation_id is None:
            return
        if not metadata:
            return

        dataframe_output_names = tuple(
            output_name
            for output_name, output in outputs.items()
            if isinstance(output.value, dd.DataFrame)
        )
        if not dataframe_output_names:
            return
        if any(
            output_name not in metadata or metadata[output_name] is None
            for output_name in dataframe_output_names
        ):
            logger.warning("Skip dataframe execution snapshot without complete metadata for node {}", self.node_id)
            return

        try:
            await cache.stage_execution_snapshot(
                project_id=self.project_id,
                node_id=self.node_id,
                generation_id=generation_id,
                node_name=self.__class__.__name__,
                node_runtime_fingerprint=self._dataframe_cache_runtime_fingerprint,
                output_names=tuple(outputs),
                dataframe_output_names=dataframe_output_names,
                non_dataframe_outputs={
                    output_name: output
                    for output_name, output in outputs.items()
                    if output_name not in dataframe_output_names
                },
                metadata=dict(metadata),
                execution_order=self._dataframe_cache_execution_order,
            )
        except Exception:
            logger.exception("Failed to stage dataframe cache snapshot for node {}", self.node_id)
            if self._dataframe_cache_policy.strict:
                raise

    @classmethod
    async def restore_execution_snapshot(
            cls,
            *,
            project_id: str,
            node_id: str,
            node_name: str,
            expected_output_names: tuple[str, ...],
            data_store: "ObjectStore[Any]",
            data_index_store: "IndexStore[Any, Any]",
            node_runtime_fingerprint: str | None = None,
    ) -> MetadataCacheEntry | None:
        del data_index_store  # generation cache uses manifests, not partition index scans
        cache = DataFrameExecutionCache(data_store=data_store)
        try:
            plan = await cache.get_restore_plan(
                project_id=project_id,
                node_id=node_id,
                node_name=node_name,
                node_runtime_fingerprint=node_runtime_fingerprint,
                expected_output_names=expected_output_names,
            )
        except Exception:
            logger.exception("Failed to read dataframe cache restore plan for node {}", node_id)
            return None
        if plan is None:
            return None

        restored_outputs = dict(plan.snapshot.non_dataframe_outputs)
        for output_name, manifest in plan.manifests.items():
            restored_outputs[output_name] = NodeOutput(
                value=build_lazy_dataframe(cache, manifest)
            )

        if set(restored_outputs) != set(expected_output_names):
            return None
        return MetadataCacheEntry.create(
            outputs=restored_outputs,
            metadata=plan.snapshot.metadata,
        )

    async def execute(self, mode: PipelineExecutionMode) -> None:
        if mode == PipelineExecutionMode.FULL:
            mode = None  # Чтобы получить все хуки

        if mode == PipelineExecutionMode.METADATA_ONLY:
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
            self.process()

        if mode == PipelineExecutionMode.METADATA_ONLY:
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

        if mode is None:
            async_worker.ensure_own_loop()

            total_npartitions = 0
            ddfs: list[DDFOutputMeta] = []
            for _, field in self._output_field_instances.items():
                output = getattr(self, field.attr_name)
                if not isinstance(output, dd.DataFrame):
                    continue
                total_npartitions += output.npartitions
                ddfs.append(DDFOutputMeta(
                    attr_name=field.attr_name,
                    npartitions=output.npartitions,
                    ddf=output,
                ))

            cache: DataFrameExecutionCache | None = None
            generation_id: str | None = None
            if self._store_enabled:
                if self.data_store is None:
                    logger.warning(
                        "store_enabled=True but data store is not configured; dataframe cache will be skipped."
                    )
                else:
                    cache = DataFrameExecutionCache(
                        data_store=self.data_store,
                        ttl_lifetime=self._execution_cache_ttl(),
                        policy=self._dataframe_cache_policy,
                    )
                    generation_id = cache.new_generation_id()
            self._dataframe_execution_cache = cache
            self._dataframe_cache_generation_id = generation_id

            callback_coordinator = _NodeCallbacksCoordinator(
                on_started=lambda: async_worker.run(self._node_started()),
                on_finished=lambda: async_worker.run(self._node_finished()),
            )
            progress_lock = threading.Lock()
            partition_dispatch_queue_size = max(
                16,
                min(512, max(total_npartitions, 1) * 2),
            )

            self.total_steps = total_npartitions
            for ddf_output_meta in ddfs:
                writer: DaskPartitionCacheWriter | None = None
                if cache is not None and generation_id is not None:
                    try:
                        await cache.begin_output_generation(
                            project_id=self.project_id,
                            node_id=self.node_id,
                            output_name=ddf_output_meta.attr_name,
                            generation_id=generation_id,
                            node_runtime_fingerprint=self._dataframe_cache_runtime_fingerprint,
                            meta=ddf_output_meta.ddf._meta,
                            npartitions=ddf_output_meta.npartitions,
                            known_divisions=ddf_output_meta.ddf.known_divisions,
                            divisions=(
                                tuple(ddf_output_meta.ddf.divisions)
                                if ddf_output_meta.ddf.known_divisions
                                else None
                            ),
                        )
                        writer = DaskPartitionCacheWriter(
                            cache=cache,
                            project_id=self.project_id,
                            node_id=self.node_id,
                            output_name=ddf_output_meta.attr_name,
                            generation_id=generation_id,
                            npartitions=ddf_output_meta.npartitions,
                            policy=self._dataframe_cache_policy,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to begin dataframe cache generation for {}.{}",
                            self.node_id,
                            ddf_output_meta.attr_name,
                        )
                        if self._dataframe_cache_policy.strict:
                            raise

                partition_context = DDFPartitionCallbackContext(
                    writer=writer,
                    progress_step=self.progress_step,
                    progress_lock=progress_lock,
                )
                callback_metadata = {
                    "callback_coordinator": callback_coordinator,
                    "partition_context": partition_context,
                }
                operation_id = f"{self.task_id}:{self.node_id}:{ddf_output_meta.attr_name}"

                output = ddf_output_meta.ddf.add_callbacks(
                    on_start=_on_operation_start,
                    on_end=_on_operation_end,
                    on_partition=_on_operation_partition,
                    on_error=_on_operation_error,
                    metadata=callback_metadata,
                    metadata_token=operation_id,
                    operation_id=operation_id,
                    operation_type="node_df_output",
                    copy_meta_mode="none",
                    copy_partition_mode="none",
                    partition_dispatch_mode="sync" if writer is not None else "threaded",
                    partition_dispatch_workers=1,
                    partition_dispatch_queue_size=partition_dispatch_queue_size,
                )
                setattr(self, ddf_output_meta.attr_name, output)
