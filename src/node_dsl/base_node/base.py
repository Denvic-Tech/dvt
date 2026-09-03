from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Optional

from pydantic import BaseModel

from src import enums, utils
from src.logger import logger
from src.pipeline.execution_mode import PipelineExecutionMode

from ..exceptions import NodeValidationError
from ..field import InputField, OutputField
from ..node_meta import BaseNodeMeta
from ..node_typing import IO
from ..types import (
    OnNodeErrorCallback,
    OnNodeMetadataCallback,
    OnNodeProcessStartCallback,
    OnNodeProcessSuccessCallback,
    OnNodeProgressStepCallback,
)
from .mixins import (
    CachingNodeMixin,
    CallbackNodeMixin,
    ErrorNodeMixin,
    ExecutionNodeMixin,
    ExtensionNodeMixin,
    IdentityNodeMixin,
    IOFieldsNodeMixin,
    MetadataNodeMixin,
    ProgressNodeMixin,
    ProjectSettingsNodeMixin,
    ProjectVariablesNodeMixin,
    SystemVariablesNodeMixin,
    ValidateNodeMixin,
    VariablePortsNodeMixin,
)

if TYPE_CHECKING:
    from src.modules.pipeline_cache import (
        CommonOutputKey,
        DataIndexEntry,
        IndexStore,
        MetadataCacheEntry,
        MetaKey,
        ObjectStore,
    )
    from src.pipeline.processor import PipelineProcessor
    from src.schemas.internal import ProjectSettings, ProjectVariables


class BaseNode(
    IOFieldsNodeMixin,
    IdentityNodeMixin,
    MetadataNodeMixin,
    ProgressNodeMixin,
    CallbackNodeMixin,
    ValidateNodeMixin,
    CachingNodeMixin,
    ErrorNodeMixin,
    ProjectSettingsNodeMixin,
    ProjectVariablesNodeMixin,
    VariablePortsNodeMixin,
    SystemVariablesNodeMixin,
    ExtensionNodeMixin,
    ExecutionNodeMixin,
    ABC,
    metaclass=BaseNodeMeta
):
    """
    Базовый класс для всех нод ETL пайплайна на основе Pydantic.

    Использует метакласс BaseNodeMeta для автоматической конфигурации
    Pydantic полей и сбора метаданных ноды.
    """
    # --- Атрибуты класса для метаданных ---
    TITLE: ClassVar[str | None] = None
    EMOJI: ClassVar[str | None] = None
    CATEGORY: ClassVar[str] = "Custom"
    TAGS: ClassVar[list[str]] = []
    TYPE: ClassVar[enums.NodeType] = enums.NodeType.BASE
    OUTPUT_NODE: ClassVar[bool] = False
    DESCRIPTION: ClassVar[str | None] = None
    DEPRECATED: ClassVar[bool] = False
    EXPERIMENTAL: ClassVar[bool] = False
    VISIBLE: ClassVar[bool] = True
    DISABLED: ClassVar[bool] = False
    ADDITIONAL_SCHEMA: ClassVar[dict | None] = None
    CACHABLE: ClassVar[bool] = True
    TTL_CACHE: ClassVar[int | None] = False
    EXTENSION_NAME: ClassVar[str | None] = None
    EXTENSION_VERSION: ClassVar[str | None] = None
    SYSTEM_VARIABLES_MODEL: ClassVar[type[BaseModel] | None] = None
    METADATA_VARIABLE_PREPASS_INPUTS: ClassVar[frozenset[str]] = frozenset()
    CAN_BE_OUTPUT_NODE: ClassVar[bool] = True
    AUTO_ACTIVATE_SIGNAL_OUTPUTS: ClassVar[bool] = True
    DISABLED_OUTPUTS: ClassVar[Sequence[str] | None] = None

    input_variables: dict[str, IO.VARIABLE] = InputField(
        default={},
        description="Input variables",
        allow_multiple_connections=True
    )
    signal_in: Optional[IO.SIGNAL] = InputField(
        default=None,
        description="Execution signal input",
        allow_multiple_connections=True
    )

    output_variables: dict[str, IO.VARIABLE] = OutputField(description="Output variables")
    signal_out: IO.SIGNAL = OutputField(description="Execution signal output")
    signal_error: IO.SIGNAL = OutputField(description="Execution error signal output")

    def __init__(
            self,
            *,
            user_id: str,
            project_id: str,
            task_id: str,
            node_id: str,

            on_process_start: OnNodeProcessStartCallback | None = None,
            on_process_success: OnNodeProcessSuccessCallback | None = None,
            on_error: OnNodeErrorCallback | None = None,
            on_node_metadata: OnNodeMetadataCallback | None = None,
            on_progress_step: OnNodeProgressStepCallback | None = None,

            # Data Stores
            data_store: Optional["ObjectStore[Any]"] = None,
            data_index_store: Optional["IndexStore[CommonOutputKey, DataIndexEntry]"] = None,

            # Metadata Stores
            metadata_store: Optional["ObjectStore[MetadataCacheEntry]"] = None,
            metadata_index_store: Optional["IndexStore[MetaKey, str]"] = None,

            store_enabled: bool | None = False,

            # Project Settings
            project_settings: Optional["ProjectSettings"] = None,

            # Project Variables
            project_variables: Optional["ProjectVariables"] = None,

            # Execution data
            execution_mode: PipelineExecutionMode | None = None,
            execution_settings=None,

            **input_kwargs
    ):
        super().__init__(
            user_id=user_id,
            project_id=project_id,
            task_id=task_id,
            node_id=node_id,

            on_process_start=on_process_start,
            on_process_success=on_process_success,
            on_error=on_error,
            on_node_metadata=on_node_metadata,
            on_progress_step=on_progress_step,

            data_store=data_store,
            data_index_store=data_index_store,

            metadata_store=metadata_store,
            metadata_index_store=metadata_index_store,

            store_enabled=store_enabled,

            project_settings=project_settings,
            project_variables=project_variables,

            execution_mode=execution_mode,
            execution_settings=execution_settings,
        )

        self._set_kwargs(**input_kwargs)
        self._normalize_variable_ports()

    def _set_kwargs(self, **input_kwargs):
        input_field_names = {field.attr_name for field in self._input_field_instances.values()}
        for k, v in input_kwargs.items():
            if k not in input_field_names:
                raise NodeValidationError(f"Unknown input field '{k}' for node '{self.__class__.__name__}'")
            # Some pipeline builders/UI layers may send Ellipsis as a sentinel for "no value".
            # Treat it as "not provided" to preserve class defaults and let validation decide
            # requiredness based on the field definition.
            if v is Ellipsis:
                continue
            setattr(self, k, v)

    @classmethod
    def from_pipeline_processor(
            cls,
            *,
            pipeline_processor: "PipelineProcessor",

            node_id: str,

            on_process_start: OnNodeProcessStartCallback | None = None,
            on_process_success: OnNodeProcessSuccessCallback | None = None,
            on_progress_step: OnNodeProgressStepCallback | None = None,

            store_enabled: bool | None = False,

            **input_kwargs
    ):
        return cls(
            node_id=node_id,
            user_id=pipeline_processor.task.user_id,
            project_id=pipeline_processor.task.project_id,
            task_id=pipeline_processor.task.task_id,

            on_process_start=on_process_start,
            on_process_success=on_process_success,
            on_progress_step=on_progress_step,

            data_store=pipeline_processor.data_store,
            data_index_store=pipeline_processor.data_index_store,

            metadata_store=pipeline_processor.metadata_store,
            metadata_index_store=pipeline_processor.metadata_index_store,

            store_enabled=store_enabled,

            project_settings=pipeline_processor.task.project_settings,
            project_variables=pipeline_processor.task.project_variables,

            execution_mode=pipeline_processor.task.mode,
            execution_settings=pipeline_processor.execution_settings,

            **input_kwargs
        )

    @abstractmethod
    def process(self) -> None:
        """
        Основной метод обработки данных ноды.
        Должен быть реализован в дочерних классах.

        Входные данные доступны через self.имя_входного_атрибута.
        Результаты должны быть присвоены выходным атрибутам:
        self.имя_выходного_атрибута = результат
        """
        raise NotImplementedError("'process' method should be implemented")

    async def process_metadata(self) -> None:
        logger.warning(
            "Node '{}' does not override process_metadata(); falling back to process().",
            self.__class__.__name__,
        )
        await utils.async_run_callable(self.process, offload_sync=False)
