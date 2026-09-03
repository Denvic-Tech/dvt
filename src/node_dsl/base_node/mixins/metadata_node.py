from typing import TYPE_CHECKING, Any, Optional

from src import utils
from src.node_dsl.constants import (
    NODE_METADATA_EXCLUDE_INPUT_NAMES,
    NODE_METADATA_EXCLUDE_TYPES,
    NodeOutputNames,
)
from src.node_dsl.variables import build_variable_map_metadata

import config

from .base import BaseNodeMixin

if TYPE_CHECKING:
    from src.node_dsl.field import OutputField
    from src.node_dsl.types import NodeMetadata, NodeOutputMetadata, OnNodeMetadataCallback

_NODE_METADATA_EXCLUDE_TYPES = {str(io_type) for io_type in NODE_METADATA_EXCLUDE_TYPES}


def _is_variable_output_type(output_type: Any) -> bool:
    if isinstance(output_type, list):
        return any(_is_variable_output_type(item) for item in output_type)
    return str(output_type) in {"VARIABLE", "IO.VARIABLE"}


def _is_variable_output_field(field: Any) -> bool:
    return any([
        field.attr_name == NodeOutputNames.VARIABLES,
        _is_variable_output_type(getattr(field, "assigned_type", None)),
        _is_variable_output_type(getattr(field, "resolved_type", None)),
    ])


def _get_metadata(value: Any) -> "NodeOutputMetadata":
    from core.metadata import get_metadata

    return get_metadata(value, fernet_key=config.SECURITY.FERNET_KEY)


class MetadataNodeMixin(BaseNodeMixin):
    """
    Миксин для нод, которые могут предоставлять метаданные
    """

    def __init__(
            self,
            *args,
            on_node_metadata: Optional["OnNodeMetadataCallback"] = None,
            **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self._metadata_cb = on_node_metadata

    def infer_metadata(self) -> Optional["NodeMetadata"]:
        """
        Метод для мзвлечении метаданных ноды по выходам.
        """
        return None

    @staticmethod
    def _filter_metadata(metadata: "NodeMetadata", output_field_instances: dict[str, Any]) -> "NodeMetadata":
        return {
            attr_name: output_metadata
            for attr_name, output_metadata in metadata.items()
            if all([
                attr_name in output_field_instances,
                attr_name not in NODE_METADATA_EXCLUDE_INPUT_NAMES,
                output_field_instances[attr_name].assigned_type not in _NODE_METADATA_EXCLUDE_TYPES,
            ])
        }

    def _build_default_metadata(self) -> "NodeMetadata":
        return {
            field.attr_name: (
                build_variable_map_metadata(getattr(self, field.attr_name))
                if _is_variable_output_field(field)
                else _get_metadata(getattr(self, field.attr_name))
            )
            for field in self._output_field_instances.values()
            if all([
                field.attr_name not in NODE_METADATA_EXCLUDE_INPUT_NAMES,
                str(field.assigned_type) not in _NODE_METADATA_EXCLUDE_TYPES,
            ])
        }

    async def resolve_metadata(self) -> "NodeMetadata":
        if "_resolved_metadata" in self.__dict__:
            return self.__dict__["_resolved_metadata"]

        metadata = await utils.async_run_callable(self.infer_metadata)
        resolved_metadata = (
            self._filter_metadata(metadata, self._output_field_instances)
            if metadata is not None
            else self._build_default_metadata()
        )
        self.__dict__["_resolved_metadata"] = resolved_metadata
        return resolved_metadata
