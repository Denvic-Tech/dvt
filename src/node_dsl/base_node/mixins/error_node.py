from typing import Optional
from typing import TYPE_CHECKING

from .base import BaseNodeMixin

if TYPE_CHECKING:
    from src.node_dsl.types import OnNodeErrorCallback


class ErrorNodeMixin(BaseNodeMixin):

    def __init__(
            self,
            *args,
            on_error: Optional["OnNodeErrorCallback"] = None,
            **kwargs
    ):
        super().__init__(*args, **kwargs)

        self._error_cb = on_error
