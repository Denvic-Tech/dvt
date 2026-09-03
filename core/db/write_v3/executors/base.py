from __future__ import annotations

from abc import ABC, abstractmethod

import dask.dataframe as dd
import sqlalchemy as sa

from core.db.write_v3.models import WritePlan, WriteRequest, WriteResult


class WriteExecutor(ABC):
    def __init__(self, engine: sa.Engine, dialect) -> None:
        self.engine = engine
        self.dialect = dialect

    @abstractmethod
    def execute(self, ddf: dd.DataFrame, request: WriteRequest, plan: WritePlan) -> WriteResult:
        raise NotImplementedError
