from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import dask.dataframe as dd
import pandas as pd
import pytest
import sqlalchemy as sa
from sqlalchemy import text

from core.db.write_v3 import (
    WriteMode as WriteModeV3,
    WriteRequest as WriteRequestV3,
    WriteTarget as WriteTargetV3,
    write_dataframe as write_dataframe_v3,
)
from core.db.write_v4 import (
    WriteMode as WriteModeV4,
    WriteRequest as WriteRequestV4,
    WriteTarget as WriteTargetV4,
    write_dataframe as write_dataframe_v4,
)


@dataclass(frozen=True)
class _WriterCase:
    name: str
    make_request: Callable[[str], object]
    write: Callable[[dd.DataFrame, sa.Engine, object], object]


WRITERS = [
    _WriterCase(
        name="v3",
        make_request=lambda table_name: WriteRequestV3(
            mode=WriteModeV3.APPEND,
            target=WriteTargetV3(table_name=table_name),
            chunksize=100,
            write_workers=1,
        ),
        write=write_dataframe_v3,
    ),
    _WriterCase(
        name="v4",
        make_request=lambda table_name: WriteRequestV4(
            mode=WriteModeV4.APPEND,
            target=WriteTargetV4(table_name=table_name),
            chunksize=100,
            write_workers=1,
        ),
        write=write_dataframe_v4,
    ),
]


def _engine(tmp_path: Path, suffix: str) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{tmp_path / f'write_index_{suffix}.sqlite'}")


@pytest.mark.parametrize("writer", WRITERS, ids=lambda case: case.name)
def test_db_writer_uses_ordinary_column_for_dual_role_business_index(tmp_path, writer: _WriterCase):
    engine = _engine(tmp_path, f"{writer.name}_dual")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (id INTEGER, value TEXT)"))

    pdf = pd.DataFrame({"id": [1, 2], "value": ["a", "b"]})
    pdf.index = pd.Index(pdf["id"], name="id")
    ddf = dd.from_pandas(pdf, npartitions=2, sort=True)

    result = writer.write(ddf, engine, writer.make_request("events"))

    assert result.rows_written == 2
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, value FROM events ORDER BY id")).fetchall()
    assert rows == [(1, "a"), (2, "b")]


@pytest.mark.parametrize("writer", WRITERS, ids=lambda case: case.name)
def test_db_writer_does_not_restore_dropped_business_field_from_internal_index(tmp_path, writer: _WriterCase):
    engine = _engine(tmp_path, f"{writer.name}_internal")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (value TEXT)"))

    pdf = pd.DataFrame({"value": ["a", "b"]})
    pdf.index = pd.Index([1, 2], name="__dvt_partition_key")
    ddf = dd.from_pandas(pdf, npartitions=2, sort=True)

    result = writer.write(ddf, engine, writer.make_request("events"))

    assert result.rows_written == 2
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT value FROM events ORDER BY value")).fetchall()
    assert rows == [("a",), ("b",)]


@pytest.mark.parametrize("writer", WRITERS, ids=lambda case: case.name)
def test_db_writer_preserves_genuine_user_index_only_field(tmp_path, writer: _WriterCase):
    engine = _engine(tmp_path, f"{writer.name}_index_only")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (id INTEGER, value TEXT)"))

    pdf = pd.DataFrame({"value": ["a", "b"]}, index=pd.Index([1, 2], name="id"))
    ddf = dd.from_pandas(pdf, npartitions=2, sort=True)

    result = writer.write(ddf, engine, writer.make_request("events"))

    assert result.rows_written == 2
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, value FROM events ORDER BY id")).fetchall()
    assert rows == [(1, "a"), (2, "b")]
