from typing import Optional
from typing import TYPE_CHECKING

from .base import BaseNodeMixin

if TYPE_CHECKING:
    from src.node_dsl.types import OnNodeProgressStepCallback
    from ..base import BaseNode


class ProgressNodeMixin(BaseNodeMixin):
    """
    Миксин для отслеживания прогресса ноды
    """

    def __init__(
            self,
            *args,
            on_progress_step: Optional["OnNodeProgressStepCallback"] = None,
            **kwargs
    ):
        super().__init__(*args, **kwargs)

        self._total_steps = 1
        self._current_step = 0
        self._progress_cb = on_progress_step

    @property
    def total_steps(self) -> int:
        return self._total_steps

    @total_steps.setter
    def total_steps(self, value: int) -> None:
        self._total_steps = value

    def progress_step(self: "BaseNode", step: int = 1) -> None:
        self._current_step += step
        if self._progress_cb:
            self._progress_cb(
                user_id=self._user_id,
                project_id=self._project_id,
                task_id=self._task_id,
                node=self,
                current_step=self._current_step,
                total_steps=self._total_steps
            )
