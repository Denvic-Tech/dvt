"""Public DVT node DSL API."""
from typing import TYPE_CHECKING

from .base_node import (
    BaseNode,
    DFOutputBaseNode,
    FTPConnectionOutputBaseNode,
    InternalBaseNode,
    JSONOutputBaseNode,
    KafkaConnectionOutputBaseNode,
    PrimitiveBaseNode,
    S3ConnectionOutputBaseNode,
    SignalOutputBaseNode,
    SMBConnectionOutputBaseNode,
    SqlConnectionOutputBaseNode,
    TestingBaseNode,
    WidgetBaseNode,
)
from .connection_types import (
    FileConnectionRecord,
    FTPConnectionRecord,
    KafkaConnectionRecord,
    S3ConnectionRecord,
    SMBConnectionRecord,
    SqlConnectionRecord,
)
from .exceptions import NodeDSLException, NodeValidationError
from .execution_settings import ExecutionDateTimePrecision, ExecutionSettings
from .field import InputField, OutputField
from .node_mixins.base import NodeFieldsMixin
from .node_typing import IO
from .registry import (
    add_definition,
    add_hook,
    add_node,
    build_definition,
    build_hooks,
    get_all_definitions,
    get_all_hooks,
    get_all_nodes,
    get_definition,
    get_hooks,
    get_node,
    run_hooks,
    run_hooks_async,
)

if TYPE_CHECKING:
    from .runtime.integrations.file_connection.mixin import FileConnectionInputMixin


def __getattr__(name: str):
    """Load legacy runtime exports only when they are explicitly requested."""
    if name == "FileConnectionInputMixin":
        from .runtime.integrations.file_connection.mixin import FileConnectionInputMixin

        return FileConnectionInputMixin
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "IO",
    "BaseNode",
    "DFOutputBaseNode",
    "ExecutionDateTimePrecision",
    "ExecutionSettings",
    "FTPConnectionOutputBaseNode",
    "FTPConnectionRecord",
    "FileConnectionInputMixin",
    "FileConnectionRecord",
    "InputField",
    "InternalBaseNode",
    "JSONOutputBaseNode",
    "KafkaConnectionOutputBaseNode",
    "KafkaConnectionRecord",
    "NodeDSLException",
    "NodeFieldsMixin",
    "NodeValidationError",
    "OutputField",
    "PrimitiveBaseNode",
    "S3ConnectionOutputBaseNode",
    "S3ConnectionRecord",
    "SMBConnectionOutputBaseNode",
    "SMBConnectionRecord",
    "SignalOutputBaseNode",
    "SqlConnectionOutputBaseNode",
    "SqlConnectionRecord",
    "TestingBaseNode",
    "WidgetBaseNode",
    "add_definition",
    "add_hook",
    "add_node",
    "build_definition",
    "build_hooks",
    "get_all_definitions",
    "get_all_hooks",
    "get_all_nodes",
    "get_definition",
    "get_hooks",
    "get_node",
    "run_hooks",
    "run_hooks_async",
]
