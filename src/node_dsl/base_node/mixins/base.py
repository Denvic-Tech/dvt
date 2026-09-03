from typing import TYPE_CHECKING, Any, ClassVar, Optional

from src.node_dsl.field import InputField, OutputField

if TYPE_CHECKING:
    from src.modules.pipeline_cache import (
        CommonOutputKey,
        DataIndexEntry,
        IndexStore,
        MetadataCacheEntry,
        MetaKey,
        ObjectStore,
    )
    from src.node_dsl.execution_settings import ExecutionSettings
    from src.node_dsl.types import (
        OnNodeErrorCallback,
        OnNodeMetadataCallback,
        OnNodeProcessStartCallback,
        OnNodeProcessSuccessCallback,
        OnNodeProgressStepCallback,
    )
    from src.schemas.internal import ProjectSettings


class BaseNodeMixin:
    # IO Fields
    _input_field_instances: ClassVar[dict[str, InputField]] = {}
    _output_field_instances: ClassVar[dict[str, OutputField]] = {}

    # Identity
    _user_id: str
    _project_id: str
    _task_id: str
    _node_id: str

    # Callbacks
    _process_start_cb: Optional["OnNodeProcessStartCallback"]
    _process_success_cb: Optional["OnNodeProcessSuccessCallback"]

    # Error
    _error_cb: Optional["OnNodeErrorCallback"]

    # Metadata
    _metadata_cb: Optional["OnNodeMetadataCallback"]

    # Progress
    _progress_cb: Optional["OnNodeProgressStepCallback"]

    # Caching
    data_store: Optional["ObjectStore[Any]"]
    data_index_store: Optional["IndexStore[CommonOutputKey, DataIndexEntry]"]

    metadata_store: Optional["ObjectStore[MetadataCacheEntry]"]
    metadata_index_store: Optional["IndexStore[MetaKey, str]"]

    _store_enabled: bool | None

    # Project Settings
    _project_settings: Optional["ProjectSettings"]

    execution_settings: "ExecutionSettings"
