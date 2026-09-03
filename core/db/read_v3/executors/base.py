from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from core.db.read_v3.models import ReadSegment, ReadV3Plan


class Executor(ABC):
    @abstractmethod
    def load_partition(self, plan: ReadV3Plan, segment: ReadSegment) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def build_meta(self, plan: ReadV3Plan) -> pd.DataFrame:
        raise NotImplementedError
