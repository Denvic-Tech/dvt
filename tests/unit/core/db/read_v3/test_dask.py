from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from core.db.read_v3.dask import frame_from_executor
from core.db.read_v3.errors import ReadV3PlanningError
from core.db.read_v3.models import (
    PartitionStrategy,
    ReadMode,
    ReadSegment,
    ReadV3Plan,
    SegmentDivision,
    ValueKind,
)


@dataclass
class _StubExecutor:
    def load_partition(self, plan: ReadV3Plan, segment: ReadSegment) -> pd.DataFrame:
        frame = pd.DataFrame({"id": [segment.division.start], "value": [segment.label]})
        frame["value"] = frame["value"].astype(object)
        frame.index = frame["id"]
        return frame

    def build_meta(self, plan: ReadV3Plan) -> pd.DataFrame:
        frame = pd.DataFrame(
            {
                "id": pd.Series(dtype="int64"),
                "value": pd.Series(dtype="object"),
            }
        )
        frame.index = pd.Index([], dtype="int64", name="id")
        return frame


def _plan() -> ReadV3Plan:
    segments = [
        ReadSegment(
            label="a",
            predicate_sql="id = 1",
            order_by_sql="ORDER BY id ASC",
            division=SegmentDivision(start=1, end=2),
            strategy=PartitionStrategy.RANGE,
        ),
        ReadSegment(
            label="b",
            predicate_sql="id = 2",
            order_by_sql="ORDER BY id ASC",
            division=SegmentDivision(start=2, end=3),
            strategy=PartitionStrategy.RANGE,
        ),
    ]
    return ReadV3Plan(
        mode=ReadMode.TABLE,
        dialect="sqlite",
        cte_prefix_sql=None,
        relation_sql="FROM test",
        select_exprs=["id", "value"],
        output_columns=["id", "value"],
        partition_key_name="id",
        partition_key_kind=ValueKind.NUMERIC,
        strategy=PartitionStrategy.RANGE,
        segments=segments,
        divisions=(1, 2, 3),
        max_rows_per_partition=1000,
    )


def test_frame_from_executor_has_known_divisions() -> None:
    plan = _plan()
    ddf = frame_from_executor(_StubExecutor(), plan)

    assert ddf.known_divisions is True
    assert ddf.divisions == (1, 2, 3)
    result = ddf.compute()
    assert len(result) == 2


def test_frame_from_executor_rejects_empty_segments() -> None:
    plan = _plan()
    plan.segments = []

    with pytest.raises(ReadV3PlanningError):
        frame_from_executor(_StubExecutor(), plan)


@dataclass
class _JsonStubExecutor:
    def load_partition(self, plan: ReadV3Plan, segment: ReadSegment) -> pd.DataFrame:
        payload = {"alpha": 1} if segment.label == "a" else ["beta", 2]
        frame = pd.DataFrame({"id": [segment.division.start], "payload": [payload]})
        frame["payload"] = frame["payload"].astype(object)
        frame.index = frame["id"]
        return frame

    def build_meta(self, plan: ReadV3Plan) -> pd.DataFrame:
        frame = pd.DataFrame(
            {
                "id": pd.Series(dtype="int64"),
                "payload": pd.Series(dtype="object"),
            }
        )
        frame.index = pd.Index([], dtype="int64", name="id")
        return frame


def test_frame_from_executor_preserves_json_object_dtype() -> None:
    plan = _plan()
    plan.select_exprs = ["id", "payload"]
    plan.output_columns = ["id", "payload"]
    plan.output_column_kinds = {"id": ValueKind.NUMERIC, "payload": ValueKind.JSON}

    ddf = frame_from_executor(_JsonStubExecutor(), plan)
    result = ddf.compute().reset_index(drop=True).sort_values("id").reset_index(drop=True)

    assert result["payload"].dtype == object
    assert result["payload"].tolist() == [{"alpha": 1}, ["beta", 2]]
