import time
from typing import TYPE_CHECKING

from src.node_dsl.input_expressions import ImmutableProjectVariables

from .base import BaseNodeMixin

if TYPE_CHECKING:
    from src.schemas.internal import ProjectVariables


class ProjectVariablesNodeMixin(BaseNodeMixin):

    def __init__(
            self,
            *args,
            project_variables: "ProjectVariables" = None,
            **kwargs
    ):
        super().__init__(*args, **kwargs)
        self._project_variables = project_variables

    @property
    def project_variables(self) -> "ProjectVariables":
        return self._project_variables

    @property
    def immutable_project_variables(self) -> ImmutableProjectVariables:
        raw_values = getattr(self._project_variables, "raw_values", {}) or {}
        return ImmutableProjectVariables(raw_values)

    def __dask_tokenize__(self):
        return f"{self.__class__.__name__}({getattr(self, "_node_id" or time.time())})"
