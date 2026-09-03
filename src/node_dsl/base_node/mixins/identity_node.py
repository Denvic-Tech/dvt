from .base import BaseNodeMixin


class IdentityNodeMixin(BaseNodeMixin):

    def __init__(
            self,
            *args,
            user_id: str,
            project_id: str,
            task_id: str,
            node_id: str,
            **kwargs
    ):
        super().__init__(*args, **kwargs)
        self._user_id = user_id
        self._project_id = project_id
        self._task_id = task_id
        self._node_id = node_id

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def project_id(self) -> str:
        return self._project_id

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def node_id(self) -> str:
        return self._node_id

    def __dask_tokenize__(self):
        return f"{self.__class__.__name__}({self._user_id}, {self._project_id}, {self._task_id}, {self._node_id})"
