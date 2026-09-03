from __future__ import annotations

from contextlib import nullcontext
from typing import Optional

import dask
import pandas as pd
from dask import dataframe as dd, delayed

from core.db.read_v3.errors import ReadV3PlanningError
from core.db.read_v3.executors.base import Executor
from core.db.read_v3.models import ReadV3Plan, ValueKind
from core.db.read_v3.partitioning.divisions import validate_divisions


def frame_from_executor(
    executor: Executor,
    plan: ReadV3Plan,
    *,
    meta: Optional[pd.DataFrame] = None,
) -> dd.DataFrame:
    if not plan.segments:
        raise ReadV3PlanningError("read_v3 plan has no segments; strict mode forbids empty execution graphs")

    divisions = validate_divisions(plan.divisions, expected_segments=len(plan.segments))
    delayed_parts = [delayed(executor.load_partition)(plan, segment) for segment in plan.segments]

    if meta is None:
        meta = executor.build_meta(plan)

    # Dask auto-promotes object columns with string-like payloads to StringDtype.
    # Disable that optimization for native JSON outputs so dict/list values survive compute().
    dask_context = (
        dask.config.set({"dataframe.convert-string": False})
        if any(kind == ValueKind.JSON for kind in plan.output_column_kinds.values())
        else nullcontext()
    )
    with dask_context:
        return dd.from_delayed(
            delayed_parts,
            meta=meta,
            divisions=divisions,
            verify_meta=True,
            prefix="read_v3",
        )
