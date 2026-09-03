import time
import traceback
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.hashing import get_hash
from core.types import Metadata

from src import utils
from src.exceptions import NodeInputError
from src.logger import logger
from src.modules.pipeline_cache import (
    CommonOutputKey,
    DataIndexEntry,
    IndexStore,
    MetadataCacheEntry,
    MetaKey,
    ObjectStore,
    create_node_inputs_fingerprint,
)
from src.modules.pipeline_cache.domain.dataframe_cache import DataFrameExecutionOrder
from src.modules.pipeline_cache.domain.fingerprints import create_node_runtime_fingerprint
from src.node_dsl import IO, registry
from src.node_dsl.base_node.df_output import DFOutputBaseNode
from src.node_dsl.constants import (
    DVT_ERROR_TEXT_VARIABLE_NAME,
    NodeInputNames,
    NodeOutputNames,
)
from src.node_dsl.core.input_values import (
    NodeInputConstantValue,
    NodeInputLinkValue,
    NodeRuntimeInputValues,
    iter_node_input_link_values,
    resolve_node_input_value,
)
from src.node_dsl.exceptions import NodeValidationError
from src.node_dsl.execution_settings import ExecutionSettings
from src.node_dsl.node_typing import contains_exact_io
from src.node_dsl.types import (
    NodeOutput,
    OnNodeErrorCallback,
    OnNodeMetadataCallback,
    OnNodeProcessStartCallback,
    OnNodeProcessSuccessCallback,
    OnNodeProgressStepCallback,
)
from src.node_dsl.variables import VariableOutput
from src.schemas.internal import TaskInternal

from .execution_mode import PipelineExecutionMode
from .graph_utils import (
    build_node_kwargs,
    collect_variable_source_node_ids,
    find_all_dependents,
    topological_sort,
)
from .types import (
    OnTaskCancelledCallback,
    OnTaskErrorCallback,
    OnTaskRunningCallback,
    OnTaskStartedCallback,
    OnTaskSuccessCallback,
    TaskStopEvent,
)

if TYPE_CHECKING:
    from src.node_dsl import BaseNode
    from src.schemas.node_definition import NodeDefinition, OutputDefinitionModel


@dataclass
class ProcessResult:
    success: bool
    error_message: str | None = None


# ---------- База: общая логика исполнения графа ----------

class PipelineProcessor:
    """
    Исполнитель пайплайна.
    TODO: Rename to TaskProcessor
    """

    def __init__(
            self,
            *,
            task: TaskInternal,
            stop_event: TaskStopEvent | None = None,

            # Task Callbacks
            on_task_started: OnTaskStartedCallback | None = None,
            on_task_running: OnTaskRunningCallback | None = None,
            on_task_success: OnTaskSuccessCallback | None = None,
            on_task_error: OnTaskErrorCallback | None = None,
            on_task_canceled: OnTaskCancelledCallback | None = None,

            # Node Callbacks
            on_node_process_start: OnNodeProcessStartCallback | None = None,
            on_node_process_success: OnNodeProcessSuccessCallback | None = None,
            on_node_error: OnNodeErrorCallback | None = None,
            on_node_metadata: OnNodeMetadataCallback | None = None,
            on_node_progress_step: OnNodeProgressStepCallback | None = None,

            # Data Stores
            data_store: ObjectStore[Any] | None = None,
            data_index_store: IndexStore[CommonOutputKey, DataIndexEntry] | None = None,

            # Metadata Stores
            metadata_store: ObjectStore[MetadataCacheEntry] | None = None,
            metadata_index_store: IndexStore[MetaKey, str] | None = None,
            execution_settings: ExecutionSettings | None = None,
    ):
        self.stop_event = stop_event

        self.task = task
        self.project_id = task.project_id
        self.task_id = task.task_id
        self.user_id = task.user_id
        self.pipeline = task.pipeline
        self.target_nodes = task.target_nodes
        self.changed_node_ids = task.changed_node_ids or task.metadata_changed_node_ids or []
        self.metadata_changed_node_ids = self.changed_node_ids

        self.on_task_started = on_task_started
        self.on_task_running = on_task_running
        self.on_task_success = on_task_success
        self.on_task_error = on_task_error
        self.on_task_canceled = on_task_canceled

        self.before_node_process = on_node_process_start
        self.after_node_process = on_node_process_success
        self.on_node_error = on_node_error
        self.on_node_metadata = on_node_metadata
        self.on_node_progress_step = on_node_progress_step

        self.metadata_store = metadata_store
        self.metadata_index_store = metadata_index_store

        self.data_store = data_store
        self.data_index_store = data_index_store
        self.execution_settings = execution_settings or ExecutionSettings()

        self._execution_order: list[str] | None = None
        self._planned_execution_order: list[str] | None = None
        self._affected_metadata_nodes: set[str] | None = None
        self._completed_node_ids: set[str] = set()
        self._recoverable_failed_node_ids: set[str] = set()

        # Результаты текущего запуска
        self.executed_nodes: list[str] = []
        self.failed_nodes: list[str] = []
        self.skipped_nodes: list[str] = []
        self.restored_nodes: list[str] = []

        # Данные/метаданные/хеши нод
        self.nodes_outputs: dict[str, dict[str, NodeOutput]] = defaultdict(dict)  # {node_id: {output_name: NodeOutput}}
        self.nodes_output_hashes: dict[str, dict[str, bytes]] = defaultdict(
            dict)  # {node_id: {output_name: hash_bytes}}
        self.nodes_metadata: dict[str, dict[str, Metadata]] = defaultdict(dict)  # {node_id: {output_name: Metadata}}
        self.node_signal_states: dict[str, dict[str, bool]] = defaultdict(dict)  # {node_id: {output_name: is_active}}

        logger.info(
            f"{self.__class__.__name__} initialized for project={self.project_id}, "
            f"task={self.task_id}, user={self.user_id}"
        )

    # ---------- Общая механика ----------

    def _stop_requested(self) -> bool:
        if self.stop_event:
            return self.stop_event.is_set()

        return False

    @property
    def execution_order(self) -> list[str]:
        if self._execution_order is None:
            self._execution_order = topological_sort(pipeline=self.pipeline, target_nodes=self.target_nodes)

        return self._execution_order

    @property
    def effective_execution_order(self) -> list[str]:
        if self._planned_execution_order is not None:
            return self._planned_execution_order
        return self.execution_order

    def _incremental_metadata_enabled(self) -> bool:
        return self.task.mode == PipelineExecutionMode.METADATA_ONLY and bool(self.changed_node_ids)

    def _get_affected_metadata_nodes(self) -> set[str]:
        if self._affected_metadata_nodes is None:
            self._affected_metadata_nodes = find_all_dependents(
                pipeline=self.pipeline,
                source_nodes=self.changed_node_ids,
            )
        return self._affected_metadata_nodes

    def _metadata_cache_allowed_for_node(self, node_id: str) -> bool:
        if not self._incremental_metadata_enabled():
            return True
        return node_id not in self._get_affected_metadata_nodes()

    def _cache_frontier_enabled(self) -> bool:
        return bool(
            self.changed_node_ids
            and self.data_store is not None
            and self.data_index_store is not None
        )

    def _execution_target_ids(self) -> list[str]:
        execution_node_ids = set(self.execution_order)
        explicit_targets = [
            node_id for node_id in self.target_nodes or []
            if node_id in execution_node_ids
        ]
        if explicit_targets:
            return explicit_targets

        parent_ids = {
            parent_id
            for node_id in self.execution_order
            for parent_id in self._gather_parent_ids(self.pipeline[node_id].inputs)
            if parent_id in execution_node_ids
        }
        return [node_id for node_id in self.execution_order if node_id not in parent_ids]

    def _apply_restored_entry(
            self,
            *,
            node_id: str,
            node_class: type["BaseNode"],
            output_definitions: dict[str, "OutputDefinitionModel"],
            entry: MetadataCacheEntry,
    ) -> None:
        outputs = dict(entry.outputs)
        metadata = dict(entry.metadata or {})
        self.nodes_outputs[node_id] = outputs
        self.nodes_metadata[node_id] = metadata
        self._sync_node_signal_states(
            node_id=node_id,
            node_class=node_class,
            output_definitions=output_definitions,
            outputs=outputs,
        )
        for output_name, output in outputs.items():
            self.nodes_output_hashes[node_id][output_name] = get_hash(output.value)
        self._completed_node_ids.add(node_id)
        self.restored_nodes.append(node_id)

    async def _prepare_cache_frontier(self) -> None:
        if not self._cache_frontier_enabled():
            return

        affected_node_ids = self._get_affected_metadata_nodes()
        required_node_ids: set[str] = set()
        visited_node_ids: set[str] = set()

        async def require_node(node_id: str) -> None:
            if node_id in visited_node_ids or node_id not in self.pipeline:
                return
            visited_node_ids.add(node_id)

            node_data = self.pipeline[node_id]
            node_class = registry.get_node(node_data.name)
            node_def = registry.get_definition(node_data.name)
            can_restore = all((
                node_id not in affected_node_ids,
                bool(node_data.store_enabled),
                DFOutputBaseNode in node_class.__mro__,
                not node_class.OUTPUT_NODE,
            ))
            if can_restore:
                restored = await DFOutputBaseNode.restore_execution_snapshot(
                    project_id=self.project_id,
                    node_id=node_id,
                    node_name=node_class.__name__,
                    expected_output_names=tuple(node_def.output_definitions),
                    data_store=self.data_store,
                    data_index_store=self.data_index_store,
                    node_runtime_fingerprint=create_node_runtime_fingerprint(node_class),
                )
                if restored is not None:
                    self._apply_restored_entry(
                        node_id=node_id,
                        node_class=node_class,
                        output_definitions=node_def.output_definitions,
                        entry=restored,
                    )
                    logger.debug("Restored dataframe cache frontier node {}", node_id)
                    return

            required_node_ids.add(node_id)
            for parent_id in self._gather_parent_ids(node_data.inputs):
                await require_node(parent_id)

        for target_node_id in self._execution_target_ids():
            await require_node(target_node_id)

        self._planned_execution_order = [
            node_id for node_id in self.execution_order
            if node_id in required_node_ids
        ]
        logger.debug(
            "Prepared cache frontier: restored={}, execution_order={}",
            self.restored_nodes,
            self._planned_execution_order,
        )

    @staticmethod
    def _supports_early_metadata_cache_restore(node_class: type["BaseNode"]) -> bool:
        return "get_metadata_cache_key" not in node_class.__dict__

    @staticmethod
    def _gather_parent_ids(
            node_inputs: NodeRuntimeInputValues,
    ):
        parent_ids: set[str] = set()

        for input_data in node_inputs.values():
            for link in iter_node_input_link_values(input_data):
                parent_ids.add(link.node_id)

        return parent_ids

    def _gather_parent_hashes_and_constants(
            self,
            node_id: str,
            node_def: "NodeDefinition",
            node_inputs: NodeRuntimeInputValues,
            runtime_variables: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        parent_hashes: dict[str, str] = {}
        constant_inputs: dict[str, Any] = {}

        for input_name, input_data in node_inputs.items():
            input_def = node_def.input_definitions.get(input_name)
            link_values = list(iter_node_input_link_values(input_data))
            if link_values:
                for idx, item in enumerate(link_values):
                    src_node = item.node_id
                    src_output = item.output_name
                    h = self.nodes_output_hashes.get(src_node, {}).get(src_output, b"")
                    # Keep old key format for single-link inputs; disambiguate multi-link ones.
                    if len(link_values) == 1:
                        key = f"{src_node}.{src_output}"
                    else:
                        key = f"{input_name}[{idx}]:{src_node}.{src_output}"
                    parent_hashes[key] = h.hex() if isinstance(h, (bytes, bytearray)) else str(h)
            else:
                if isinstance(input_data, NodeInputConstantValue):
                    raw_value = input_data.value
                else:
                    raw_value = input_data
                try:
                    constant_inputs[input_name] = resolve_node_input_value(
                        raw_value,
                        variables=runtime_variables,
                        target_type=getattr(input_def, "type", None),
                        is_list_type=bool(getattr(input_def, "is_list_type", False)),
                        allow_expressions=bool(getattr(input_def, "allow_expressions", True)),
                        expression_policy=getattr(input_def, "expression_policy", None),
                        allow_unresolved=self.task.mode == PipelineExecutionMode.METADATA_ONLY,
                    )
                except ValueError as err:
                    raise NodeInputError(f"Node {node_id}: {err}") from err
        return parent_hashes, constant_inputs

    def _runtime_variables_map(self, node_kwargs: dict[str, Any]) -> dict[str, Any]:
        runtime_variables: dict[str, Any] = dict(self._project_variables_map())
        linked_variables = node_kwargs.get("input_variables")
        if isinstance(linked_variables, dict):
            runtime_variables.update(linked_variables)
        return runtime_variables

    def _project_variables_map(self) -> dict[str, Any]:
        project_variables = self.task.project_variables
        if project_variables is None:
            return {}
        return project_variables.raw_values

    def _should_skip_output_node(self, node_class: type["BaseNode"]) -> bool:
        return self.task.mode == PipelineExecutionMode.METADATA_ONLY and node_class.OUTPUT_NODE

    @staticmethod
    def _is_signal_output_definition(output_def: "OutputDefinitionModel") -> bool:
        return contains_exact_io(output_def.type, IO.SIGNAL)

    @staticmethod
    def _iter_signal_links(node_inputs: NodeRuntimeInputValues) -> list[NodeInputLinkValue]:
        return list(iter_node_input_link_values(node_inputs.get(NodeInputNames.SIGNAL)))

    @staticmethod
    def _resolve_signal_output_state(
            *,
            output_name: str,
            node_output: NodeOutput | None,
            auto_activate: bool,
    ) -> bool:
        output_value = None if node_output is None else node_output.value
        if isinstance(output_value, bool):
            return output_value
        if auto_activate and output_name == NodeOutputNames.SIGNAL:
            return True
        return False

    def _sync_node_signal_states(
            self,
            *,
            node_id: str,
            node_class: type["BaseNode"],
            output_definitions: dict[str, "OutputDefinitionModel"],
            outputs: dict[str, NodeOutput],
    ) -> None:
        signal_states: dict[str, bool] = {}
        auto_activate = bool(getattr(node_class, "AUTO_ACTIVATE_SIGNAL_OUTPUTS", True))

        for output_name, output_def in output_definitions.items():
            if not self._is_signal_output_definition(output_def):
                continue
            signal_states[output_name] = self._resolve_signal_output_state(
                output_name=output_name,
                node_output=outputs.get(output_name),
                auto_activate=auto_activate,
            )

        self.node_signal_states[node_id] = signal_states

    def _has_inactive_required_signal(self, node_inputs: NodeRuntimeInputValues) -> bool:
        signal_links = self._iter_signal_links(node_inputs)
        if not signal_links:
            return False

        return not all(
            self.node_signal_states.get(link.node_id, {}).get(link.output_name, False)
            for link in signal_links
        )

    def _has_error_signal_downstream(self, node_id: str) -> bool:
        for node_data in self.pipeline.values():
            for signal_link in self._iter_signal_links(node_data.inputs):
                if (
                    signal_link.node_id == node_id
                    and signal_link.output_name == NodeOutputNames.ERROR_SIGNAL
                ):
                    return True
        return False

    def _should_skip_due_to_recoverable_parent_failure(
            self,
            node_inputs: NodeRuntimeInputValues,
    ) -> bool:
        links_by_source: dict[str, list[tuple[str, NodeInputLinkValue]]] = defaultdict(list)
        for input_name, input_data in node_inputs.items():
            for link in iter_node_input_link_values(input_data):
                if link.node_id in self._recoverable_failed_node_ids:
                    links_by_source[link.node_id].append((input_name, link))

        for source_links in links_by_source.values():
            has_error_signal_gate = any(
                input_name == NodeInputNames.SIGNAL and link.output_name == NodeOutputNames.ERROR_SIGNAL
                for input_name, link in source_links
            )
            has_invalid_link = any(
                not (
                    (input_name == NodeInputNames.SIGNAL and link.output_name == NodeOutputNames.ERROR_SIGNAL)
                    or link.output_name == NodeOutputNames.VARIABLES
                )
                for input_name, link in source_links
            )
            if not has_error_signal_gate or has_invalid_link:
                return True

        return False

    def _build_runtime_error_outputs(
            self,
            *,
            node: "BaseNode",
            error_message: str,
    ) -> dict[str, NodeOutput]:
        input_variables = getattr(node, NodeInputNames.VARIABLES, None)
        if not isinstance(input_variables, dict):
            input_variables = dict(input_variables or {})
        else:
            input_variables = dict(input_variables)

        existing_output_variables = getattr(node, NodeOutputNames.VARIABLES, None)
        if not isinstance(existing_output_variables, dict):
            existing_output_variables = {}
        else:
            existing_output_variables = dict(existing_output_variables)

        error_output_variables = dict(input_variables)
        error_output_variables.update(existing_output_variables)
        error_output_variables[DVT_ERROR_TEXT_VARIABLE_NAME] = VariableOutput(
            name=DVT_ERROR_TEXT_VARIABLE_NAME,
            type=IO.STRING,
            value=error_message,
            var_type="system",
        )

        setattr(node, NodeOutputNames.VARIABLES, error_output_variables)
        setattr(node, NodeOutputNames.SIGNAL, False)
        setattr(node, NodeOutputNames.ERROR_SIGNAL, True)

        outputs = {
            field.attr_name: NodeOutput(value=None)
            for field in node.output_fields().values()
        }
        outputs[NodeOutputNames.VARIABLES] = NodeOutput(value=error_output_variables)
        outputs[NodeOutputNames.SIGNAL] = NodeOutput(value=False)
        outputs[NodeOutputNames.ERROR_SIGNAL] = NodeOutput(value=True)
        return outputs

    def _collect_metadata_variable_prepass_source_nodes(self) -> set[str]:
        if self.task.mode != PipelineExecutionMode.METADATA_ONLY:
            return set()

        source_node_ids: set[str] = set()
        for node_id in self.effective_execution_order:
            node_data = self.pipeline[node_id]
            node_class = registry.get_node(node_data.name)
            if self._should_skip_output_node(node_class):
                continue
            if not getattr(node_class, "METADATA_VARIABLE_PREPASS_INPUTS", frozenset()):
                continue

            node_def = registry.get_definition(node_data.name)
            source_node_ids.update(
                collect_variable_source_node_ids(
                    node_def=node_def,
                    node_data=node_data,
                )
            )

        return source_node_ids

    def _prepare_metadata_variable_prepass_order(self) -> list[str]:
        source_node_ids = self._collect_metadata_variable_prepass_source_nodes()
        if not source_node_ids:
            return []

        prepass_order = topological_sort(
            pipeline=self.pipeline,
            target_nodes=sorted(source_node_ids),
        )
        effective_node_ids = set(self.effective_execution_order)
        return [node_id for node_id in prepass_order if node_id in effective_node_ids]

    async def _try_restore_node_meta_cache_and_skip(
            self,
            node_id: str,
            current_node_name: str,
            node_class: type["BaseNode"],
            meta_cache_key: str,
            output_definitions: dict[str, "OutputDefinitionModel"]
    ) -> bool:
        if self.task.mode == PipelineExecutionMode.FULL or self.metadata_store is None:
            return False

        cached = await self.metadata_store.get(meta_cache_key)
        if cached:
            logger.debug(f"Use cached metadata for node {current_node_name}(id={node_id})")

            ordered_output_names = list(output_definitions.keys())
            definition_names = set(ordered_output_names)
            cached_output_names = set(cached.outputs.keys())
            signal_output_names = {
                output_name
                for output_name, output_def in output_definitions.items()
                if self._is_signal_output_definition(output_def)
            }
            extra_output_names = cached_output_names - definition_names
            missing_output_names = definition_names - cached_output_names
            if extra_output_names or not missing_output_names.issubset(signal_output_names):
                logger.warning(
                    f"Skip stale metadata cache for node {current_node_name}(id={node_id}): "
                    f"cached outputs {cached_output_names} do not match definition {definition_names}"
                )
                return False
            normalized_outputs = {
                output_name: cached.outputs.get(output_name, NodeOutput(value=None))
                for output_name in ordered_output_names
            }

            cached_metadata = cached.metadata or {}
            cached_metadata_names = set(cached_metadata.keys())
            if not cached_metadata_names.issubset(definition_names):
                logger.warning(
                    f"Skip stale metadata cache for node {current_node_name}(id={node_id}): "
                    f"cached metadata keys {cached_metadata_names} are not compatible with definition "
                    f"{definition_names}"
                )
                return False

            normalized_metadata = {
                output_name: cached_metadata.get(output_name)
                for output_name in ordered_output_names
            }

            self.nodes_outputs[node_id] = normalized_outputs
            self.nodes_metadata[node_id] = normalized_metadata
            self._sync_node_signal_states(
                node_id=node_id,
                node_class=node_class,
                output_definitions=output_definitions,
                outputs=normalized_outputs,
            )

            for output_name, node_output in normalized_outputs.items():
                self.nodes_output_hashes[node_id][output_name] = get_hash(node_output.value)

            self._completed_node_ids.add(node_id)

            return True

        return False

    async def _try_restore_node_meta_cache_before_instantiation(
            self,
            *,
            node_id: str,
            node_class: type["BaseNode"],
            node_def: "NodeDefinition",
            node_data,
    ) -> tuple[bool, str | None]:
        if not all([
            self._incremental_metadata_enabled(),
            self._metadata_cache_allowed_for_node(node_id),
            self.metadata_store is not None,
            node_class.CACHABLE,
            self._supports_early_metadata_cache_restore(node_class),
        ]):
            return False, None

        parent_hashes, constant_inputs = self._gather_parent_hashes_and_constants(
            node_id=node_id,
            node_def=node_def,
            node_inputs=node_data.inputs,
            runtime_variables=self._project_variables_map(),
        )
        meta_cache_key = create_node_inputs_fingerprint(
            node_class=node_class,
            parent_hashes=parent_hashes,
            constant_inputs=constant_inputs,
        )
        restored = await self._try_restore_node_meta_cache_and_skip(
            node_id=node_id,
            current_node_name=node_data.name,
            node_class=node_class,
            meta_cache_key=meta_cache_key,
            output_definitions=node_def.output_definitions,
        )
        return restored, meta_cache_key

    async def _run_metadata_variable_prepass(self) -> tuple[bool, bool, bool, str | None]:
        prepass_order = self._prepare_metadata_variable_prepass_order()
        if not prepass_order:
            return False, False, False, None

        logger.debug("Run metadata variable prepass for nodes {}", prepass_order)
        first_error_message: str | None = None
        for node_id in prepass_order:
            stop_requested, should_break, task_error_reported, error_message = await self._process_node(node_id)
            if error_message is not None and first_error_message is None:
                first_error_message = error_message
            if stop_requested or should_break:
                return stop_requested, should_break, task_error_reported, first_error_message

        return False, False, False, first_error_message

    async def _process_node(self, node_id: str) -> tuple[bool, bool, bool, str | None]:
        if node_id in self._completed_node_ids:
            logger.debug("Skip node {} because it is already prepared.", node_id)
            return False, False, False, None

        node_data = self.pipeline[node_id]

        parent_ids = self._gather_parent_ids(node_data.inputs)
        if any(parent_id in self.skipped_nodes for parent_id in parent_ids):
            logger.debug(f"Skipping node {node_id} because parent node is skipped.")
            if node_id not in self.skipped_nodes:
                self.skipped_nodes.append(node_id)
            return False, False, False, None

        if self._should_skip_due_to_recoverable_parent_failure(node_data.inputs):
            logger.debug(f"Skipping node {node_id} because recoverable parent failure is not handled via signal_error.")
            if node_id not in self.skipped_nodes:
                self.skipped_nodes.append(node_id)
            return False, False, False, None

        node_class = registry.get_node(node_data.name)
        node_def = registry.get_definition(node_data.name)
        current_node_name = node_data.name

        if self._should_skip_output_node(node_class):
            logger.debug(f"Skip node {node_id} ({current_node_name}) by policy.")
            return False, False, False, None

        if self._has_inactive_required_signal(node_data.inputs):
            logger.debug(f"Skipping node {node_id} because required signal inputs are inactive.")
            if node_id not in self.skipped_nodes:
                self.skipped_nodes.append(node_id)
            return False, False, False, None

        early_meta_cache_checked = False
        early_meta_cache_key: str | None = None

        restored_early, early_meta_cache_key = await self._try_restore_node_meta_cache_before_instantiation(
            node_id=node_id,
            node_class=node_class,
            node_def=node_def,
            node_data=node_data,
        )
        if early_meta_cache_key is not None:
            early_meta_cache_checked = True
        if restored_early:
            logger.debug(f"Skip node {node_id} ({current_node_name}) by early metadata cache.")
            if self.on_node_metadata:
                cached_node_kwargs = build_node_kwargs(
                    node_id=node_id,
                    node_def=node_def,
                    node_data=node_data,
                    node_outputs=self.nodes_outputs,
                    project_variables=self._project_variables_map(),
                    execution_mode=self.task.mode,
                    node_class=node_class,
                )
                cached_node_instance = node_class.from_pipeline_processor(
                    pipeline_processor=self,
                    node_id=node_id,
                    on_process_start=self.before_node_process,
                    on_process_success=self.after_node_process,
                    on_progress_step=self.on_node_progress_step,
                    store_enabled=node_data.store_enabled,
                    **cached_node_kwargs,
                )
                await utils.async_run_callable(
                    self.on_node_metadata,
                    user_id=self.user_id,
                    project_id=self.project_id,
                    task_id=self.task_id,
                    node=cached_node_instance,
                    metadata=self.nodes_metadata[node_id],
                )
            return False, False, False, None

        node_kwargs = build_node_kwargs(
            node_id=node_id,
            node_def=node_def,
            node_data=node_data,
            node_outputs=self.nodes_outputs,
            project_variables=self._project_variables_map(),
            execution_mode=self.task.mode,
            node_class=node_class,
        )
        current_node_instance = node_class.from_pipeline_processor(
            pipeline_processor=self,
            node_id=node_id,
            on_process_start=self.before_node_process,
            on_process_success=self.after_node_process,
            on_progress_step=self.on_node_progress_step,
            store_enabled=node_data.store_enabled,
            **node_kwargs,
        )
        if DFOutputBaseNode in type(current_node_instance).__mro__:
            current_node_instance.set_dataframe_cache_execution_order(
                DataFrameExecutionOrder.from_queued_at(self.task.queued_at, self.task_id)
            )

        try:
            await current_node_instance.validate()
        except NodeValidationError as ve:
            logger.error(
                f"Validation error for node {current_node_instance.node_id} "
                f"({current_node_instance.__class__.__name__}): {ve}"
            )
            if self.on_node_error:
                await utils.async_run_callable(
                    self.on_node_error,
                    user_id=self.user_id,
                    project_id=self.project_id,
                    task_id=self.task_id,
                    node=current_node_instance,
                    message=f"Validation error: {ve}",
                )

            if node_id not in self.skipped_nodes:
                self.skipped_nodes.append(node_id)
            if node_id not in self.failed_nodes:
                self.failed_nodes.append(node_id)
            return False, False, False, (
                f"Validation error for node {current_node_instance.node_id} "
                f"({current_node_instance.__class__.__name__}): {ve}"
            )

        runtime_variables = self._runtime_variables_map(node_kwargs)
        parent_hashes, constant_inputs = self._gather_parent_hashes_and_constants(
            node_id=node_id,
            node_def=node_def,
            node_inputs=node_data.inputs,
            runtime_variables=runtime_variables,
        )

        meta_cache_key = (
                current_node_instance.get_metadata_cache_key() or
                early_meta_cache_key or
                create_node_inputs_fingerprint(
                    node_class=node_class,
                    parent_hashes=parent_hashes,
                    constant_inputs=constant_inputs,
                )
        )

        if all([
            current_node_instance.CACHABLE,
            self._metadata_cache_allowed_for_node(node_id),
            not early_meta_cache_checked,
        ]) and await self._try_restore_node_meta_cache_and_skip(
                node_id=node_id,
                current_node_name=current_node_name,
                node_class=node_class,
                meta_cache_key=meta_cache_key,
                output_definitions=node_def.output_definitions,
        ):
            logger.debug(f"Skip node {node_id} ({current_node_name}) by metadata cache.")
            if self.on_node_metadata:
                await utils.async_run_callable(
                    self.on_node_metadata,
                    user_id=self.user_id,
                    project_id=self.project_id,
                    task_id=self.task_id,
                    node=current_node_instance,
                    metadata=self.nodes_metadata[node_id],
                )
            return False, False, False, None

        try:
            logger.debug(f"Processing node {node_id} ({current_node_name}).")
            await current_node_instance.execute(mode=self.task.mode)
        except Exception as node_exec_error:
            logger.exception(f"Error executing node {node_id} ({current_node_name}): {node_exec_error}")
            error_message = str(node_exec_error)
            if self.on_node_error:
                await utils.async_run_callable(
                    self.on_node_error,
                    user_id=self.user_id,
                    project_id=self.project_id,
                    task_id=self.task_id,
                    node=current_node_instance,
                    message=error_message,
                )
            if self._has_error_signal_downstream(node_id):
                current_outputs = self._build_runtime_error_outputs(
                    node=current_node_instance,
                    error_message=error_message,
                )
                self._sync_node_signal_states(
                    node_id=node_id,
                    node_class=node_class,
                    output_definitions=node_def.output_definitions,
                    outputs=current_outputs,
                )
                for out_def in node_def.output_definitions.values():
                    out = current_outputs[out_def.attr_name]
                    self.nodes_outputs[node_id][out_def.attr_name] = out
                    self.nodes_output_hashes[node_id][out_def.attr_name] = get_hash(out.value)
                if node_id not in self.failed_nodes:
                    self.failed_nodes.append(node_id)
                self._recoverable_failed_node_ids.add(node_id)
                self._completed_node_ids.add(node_id)
                return False, False, False, error_message

            if self.task.mode == PipelineExecutionMode.METADATA_ONLY:
                if node_id not in self.failed_nodes:
                    self.failed_nodes.append(node_id)
                if node_id not in self.skipped_nodes:
                    self.skipped_nodes.append(node_id)
                return False, False, False, error_message

            if node_id not in self.failed_nodes:
                self.failed_nodes.append(node_id)
            return False, True, False, error_message

        current_outputs = current_node_instance.get_outputs()
        self._sync_node_signal_states(
            node_id=node_id,
            node_class=node_class,
            output_definitions=node_def.output_definitions,
            outputs=current_outputs,
        )
        for out_def in node_def.output_definitions.values():
            out = current_outputs[out_def.attr_name]
            self.nodes_outputs[node_id][out_def.attr_name] = out
            self.nodes_output_hashes[node_id][out_def.attr_name] = get_hash(out.value)

        resolved_metadata = await current_node_instance.resolve_metadata()

        if self.on_node_metadata:
            await utils.async_run_callable(
                self.on_node_metadata,
                user_id=self.user_id,
                project_id=self.project_id,
                task_id=self.task_id,
                node=current_node_instance,
                metadata=resolved_metadata,
            )

        if current_node_instance.CACHABLE and self.metadata_store is not None and resolved_metadata:
            await self.metadata_store.put(
                key=meta_cache_key,
                obj=MetadataCacheEntry.create(outputs=current_outputs, metadata=resolved_metadata),
                ttl_lifetime=current_node_instance.TTL_CACHE
            )
            if self.metadata_index_store is None:
                logger.warning("Metadata index store not provided, skipping metadata index caching...")
            else:
                meta_index_key = MetaKey(
                    project_id=self.project_id,
                    node_id=node_id,
                    meta_key_id=str(uuid.uuid4())
                )
                await self.metadata_index_store.put(
                    index_key=meta_index_key,
                    value=meta_cache_key,
                    ttl=current_node_instance.TTL_CACHE,
                )
            logger.debug(f"Metadata cached for '{node_def.name}'")

        if (
            self.task.mode == PipelineExecutionMode.FULL
            and DFOutputBaseNode in type(current_node_instance).__mro__
        ):
            await current_node_instance.cache_execution_snapshot(
                outputs=current_outputs,
                metadata=resolved_metadata,
            )

        self.nodes_metadata[node_id] = resolved_metadata
        self.executed_nodes.append(node_id)
        self._completed_node_ids.add(node_id)

        if self._stop_requested():
            logger.warning("Shutdown requested — stopping after finished node.")
            return True, False, False, None

        return False, False, False, None

    async def process(self) -> ProcessResult:
        logger.debug(f"{self.__class__.__name__}: run started.")
        started_at = time.time()

        if self.on_task_started:
            await utils.async_run_callable(
                self.on_task_started,
                task=self.task,
            )

        # 1) Подготовить порядок
        try:
            if not self.execution_order:
                logger.warning("No nodes to execute.")
                if self.on_task_success:
                    await utils.async_run_callable(
                        self.on_task_success,
                        task=self.task,
                    )
                return ProcessResult(success=True)

        except Exception as e:
            logger.exception("Error during graph preparation.")
            if self.on_task_error:
                await utils.async_run_callable(
                    self.on_task_error,
                    task=self.task,
                    message=str(e),
                )
            return ProcessResult(success=False, error_message=str(e))

        current_node_instance: BaseNode | None = None

        try:
            stopped = False
            had_error = False
            task_error_reported = False
            first_validation_error_message: str | None = None

            if self.on_task_running:
                await utils.async_run_callable(
                    self.on_task_running,
                    task=self.task,
                )

            await self._prepare_cache_frontier()

            stop_requested, should_break, task_error_reported, error_message = await self._run_metadata_variable_prepass()
            if error_message and first_validation_error_message is None:
                first_validation_error_message = error_message
            if error_message is not None:
                had_error = True
            if stop_requested:
                stopped = True
            if should_break:
                had_error = True

            if not stopped and not should_break:
                for node_id in self.effective_execution_order:
                    if self._stop_requested():
                        logger.warning("Shutdown requested — stop after current node (before start).")
                        stopped = True
                        break

                    stop_requested, should_break, node_task_error_reported, error_message = (
                        await self._process_node(node_id)
                    )
                    if error_message and first_validation_error_message is None:
                        first_validation_error_message = error_message
                    if error_message is not None:
                        had_error = True
                    if node_task_error_reported:
                        task_error_reported = True
                    if stop_requested:
                        stopped = True
                        break
                    if should_break:
                        had_error = True
                        break

            if stopped:
                if self.on_task_canceled:
                    await utils.async_run_callable(
                        self.on_task_canceled,
                        task=self.task,
                    )
                success = False
            elif had_error:
                result_error_message = first_validation_error_message or "Task finished with errors."
                if self.on_task_error and not task_error_reported:
                    await utils.async_run_callable(
                        self.on_task_error,
                        task=self.task,
                        message=result_error_message,
                    )
                return ProcessResult(success=False, error_message=result_error_message)
            else:
                if self.on_task_success:
                    await utils.async_run_callable(
                        self.on_task_success,
                        task=self.task,
                    )
                logger.info(f"{self.__class__.__name__}: done in {time.time() - started_at:.2f}s")
                return ProcessResult(success=True)

            logger.info(f"{self.__class__.__name__}: done in {time.time() - started_at:.2f}s")

            return ProcessResult(success=False)

        except NodeInputError as e:
            if self.on_task_error:
                await utils.async_run_callable(
                    self.on_task_error,
                    task=self.task,
                    message=str(e),
                )
            logger.error(f"Node input error: {e}")
            return ProcessResult(success=False, error_message=str(e))

        except Exception as e:
            traceback.print_exc()
            if self.on_task_error:
                await utils.async_run_callable(
                    self.on_task_error,
                    task=self.task,
                    message=str(e),
                )
            error_str = f"Unexpected error: {e}"

            if current_node_instance:
                error_str += f" ({current_node_instance.__class__.__name__}, id={current_node_instance.node_id})"

            logger.exception(error_str)
            return ProcessResult(success=False, error_message=error_str)
