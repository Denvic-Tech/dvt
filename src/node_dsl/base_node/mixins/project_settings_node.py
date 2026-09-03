import time
from typing import TYPE_CHECKING

from .base import BaseNodeMixin

if TYPE_CHECKING:
    from src.schemas.internal import ProjectSettings


class ProjectSettingsNodeMixin(BaseNodeMixin):

    def __init__(
            self,
            *args,
            project_settings: "ProjectSettings" = None,
            **kwargs
    ):
        super().__init__(*args, **kwargs)
        self._project_settings = project_settings

    @property
    def project_settings(self) -> "ProjectSettings":
        return self._project_settings

    def __dask_tokenize__(self):
        return f"{self.__class__.__name__}({getattr(self, "_node_id" or time.time())})"
