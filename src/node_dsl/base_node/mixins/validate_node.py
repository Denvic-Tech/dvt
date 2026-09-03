from typing import TYPE_CHECKING

from .base import BaseNodeMixin

from src.node_dsl.hooks import HookStage
from src.node_dsl.registry import hooks as hooks_registry
from src.node_dsl.exceptions import NodeValidationError

if TYPE_CHECKING:
    from src.node_dsl import BaseNode


class ValidateNodeMixin(BaseNodeMixin):
    async def _base_validate(self):
        for field_name, field in self._input_field_instances.items():
            field_value = getattr(self, field.attr_name)

            if not field.optional and (field_value is Ellipsis or field_value is None):
                raise NodeValidationError(f"Input '{field.attr_name}' is required but not provided.")

    async def validate(self: "BaseNode") -> None:
        await self._base_validate()
        # Lazy-build hooks to support nodes imported directly (e.g. experimental/testing nodes)
        # that were skipped by global init_nodes registration.
        if not hooks_registry.get(type(self), stage=HookStage.ON_VALIDATION):
            hooks_registry.build(type(self))
        await hooks_registry.run_async(
            node=self,
            stage=HookStage.ON_VALIDATION,
            concurrently=False,
        )
