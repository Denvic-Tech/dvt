from typing import Optional
from typing import TYPE_CHECKING

from .base import BaseNodeMixin

if TYPE_CHECKING:
    from src.node_dsl.types import (
        OnNodeProcessStartCallback,
        OnNodeProcessSuccessCallback
    )


class CallbackNodeMixin(BaseNodeMixin):

    def __init__(
            self,
            *args,
            on_process_start: Optional["OnNodeProcessStartCallback"] = None,
            on_process_success: Optional["OnNodeProcessSuccessCallback"] = None,
            **kwargs
    ):
        super().__init__(*args, **kwargs)

        self._process_start_cb = on_process_start
        self._process_success_cb = on_process_success
