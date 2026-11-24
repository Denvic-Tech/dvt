from __future__ import annotations

import collections
import threading
from decimal import Decimal
from pathlib import Path

import dask
import dask.dataframe as dd
import fsspec
import pandas as pd
import pytest
from dask.dataframe.dask_expr import _expr as dask_expr

from core.dask_lifecycle import OutputLifecycleHandlers, attach_lifecycle
from core.dask_lifecycle.tap import LifecycleTapExpr
from core.types import FsCtx

from src.nodes.write.save_csv import SaveCSV

TARGET = "reports/export.csv"

# One frame partition per piece; the middle partition is empty.
PIECES = [
    pd.DataFrame(
        {
            "n": [1, 2, 3],
            "x": [0.5, None, 1 / 3],
            "s": ["plain", 'quote"and,comma', "line\nbreak"],
            "o": [b"raw", Decimal("1.10"), None],
        },
        index=pd.Index([10, 11, 12], name="row"),
    ),
    pd.DataFrame(
        {
            "n": pd.Series([], dtype="int64"),
            "x": pd.Series([], dtype="float64"),
            "s": pd.Series([], dtype="str"),
            "o": pd.Series([], dtype=object),
        },
        index=pd.Index([], dtype="int64", name="row"),
    ),
    pd.DataFrame(
        {
            "n": [4, 5],
            "x": [2.0, -1.25],
            "s": ["Кириллица", "tab\there;semi|pipe"],
            "o": [True, 7],
        },
        index=pd.Index([20, 21], name="row"),
    ),
]


def _piece(number: int) -> pd.DataFrame:
    return PIECES[number].copy()


def _frame() -> dd.DataFrame:
    # Object columns stay object columns, as in DVT frames read with string conversion off.
    with dask.config.set({"dataframe.convert-string": False}):
        return dd.from_map(_piece, range(len(PIECES)), meta=PIECES[1], enforce_metadata=False)


def _run(df: dd.DataFrame, root: Path, **params) -> None:
    node = SaveCSV(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="save-csv-node",
        connection=object(),
        df=df,
        path=TARGET,
        **params,
    )
    node._get_fs_context = lambda *, path, **_kwargs: FsCtx(
        fs=fsspec.filesystem("file"),
        protocol="file",
        path=(root / path).as_posix(),
        storage_options={},
    )
    node.process()


def _written(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _csv(pdf: pd.DataFrame, *, sep, encoding, index, header) -> bytes:
    # Every partition is written through its own text stream: an empty chunk writes nothing,
    # and with utf-8-sig each non-empty chunk starts with a BOM (Dask's behaviour, kept as is).
    text = pdf.to_csv(sep=sep, index=index, header=header)
    return text.encode(encoding) if text else b""


def _expected(pieces, *, single_file, sep=",", encoding="utf-8", index=False, header=True):
    options = {"sep": sep, "encoding": encoding, "index": index}
    if single_file:
        # The partitions appended in order; only the first one carries the header.
        return {
            TARGET: b"".join(
                _csv(piece, header=header and number == 0, **options)
                for number, piece in enumerate(pieces)
            )
        }
    # Without '*' in the name Dask treats the target as a directory of numbered parts, and
    # every part gets the header.
    return {
        f"{TARGET}/{number}.part": _csv(piece, header=header, **options)
        for number, piece in enumerate(pieces)
    }


@pytest.mark.parametrize("single_file", [True, False], ids=["single_file", "partitioned"])
@pytest.mark.parametrize("header", [True, False], ids=["header", "no_header"])
@pytest.mark.parametrize("index", [True, False], ids=["index", "no_index"])
def test_save_csv_writes_input_partitions_unchanged(tmp_path, single_file, header, index):
    _run(_frame(), tmp_path, single_file=single_file, header=header, index=index)

    assert _written(tmp_path) == _expected(
        PIECES, single_file=single_file, header=header, index=index
    )


@pytest.mark.parametrize("single_file", [True, False], ids=["single_file", "partitioned"])
@pytest.mark.parametrize(
    ("delimiter", "sep", "encoding"),
    [
        (";", ";", "cp1251"),
        ("\\t", "\t", "utf-8-sig"),
        ("", ",", "utf-8"),
        ("|", "|", "utf-8"),
    ],
    ids=["semicolon-cp1251", "escaped-tab-bom", "blank-comma", "pipe"],
)
def test_save_csv_applies_delimiter_and_encoding(tmp_path, single_file, delimiter, sep, encoding):
    _run(
        _frame(),
        tmp_path,
        single_file=single_file,
        delimiter=delimiter,
        encoding=encoding,
    )

    assert _written(tmp_path) == _expected(
        PIECES, single_file=single_file, sep=sep, encoding=encoding
    )


@pytest.mark.parametrize("single_file", [True, False], ids=["single_file", "partitioned"])
def test_save_csv_writes_empty_dataframe(tmp_path, single_file):
    empty = PIECES[1]
    with dask.config.set({"dataframe.convert-string": False}):
        df = dd.from_pandas(empty, npartitions=1)

    _run(df, tmp_path, single_file=single_file)

    assert _written(tmp_path) == _expected([empty], single_file=single_file)


def _as_text(pdf: pd.DataFrame) -> pd.DataFrame:
    out = pdf.copy()
    out["x"] = out["x"].map(lambda value: f"v{value}").astype(object)
    return out


def test_save_csv_writes_partitions_that_differ_from_declared_meta(tmp_path):
    df = _frame().map_partitions(_as_text, meta=PIECES[1])

    _run(df, tmp_path, single_file=True)

    assert _written(tmp_path) == _expected([_as_text(piece) for piece in PIECES], single_file=True)


class _PartitionCalls:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls: collections.Counter[int] = collections.Counter()

    def __dask_tokenize__(self):
        return ("save-csv-test-partition-calls", id(self))

    def __call__(self, pdf: pd.DataFrame, partition_info=None) -> pd.DataFrame:
        with self.lock:
            self.calls[partition_info["number"]] += 1
        return pdf


def _recording_handlers(name: str, events: list[tuple], lock: threading.Lock):
    def record(kind: str, part_no: int | None = None) -> None:
        with lock:
            events.append((name, kind, part_no))

    return OutputLifecycleHandlers(
        on_start=lambda: record("start"),
        on_end=lambda: record("end"),
        on_error=lambda: record("error"),
        on_partition=lambda _partition, part_no: record("partition", part_no),
    )


@pytest.mark.parametrize("scheduler", ["threads", "sync"])
@pytest.mark.parametrize("single_file", [True, False], ids=["single_file", "partitioned"])
def test_save_csv_reports_upstream_lifecycle_once_without_fusing(
    tmp_path, monkeypatch, single_file, scheduler
):
    original_fuse = dask_expr.Expr.fuse

    def fuse_outside_input_graph(expr):
        # Blockwise fusion is superlinear on node graphs with a lifecycle tap after every node
        # and hides the taps; only the rebuilt from_delayed leaf may reach it.
        if any(isinstance(node, LifecycleTapExpr) for node in expr.walk()):
            raise AssertionError("SaveCSV must not run Dask blockwise fusion on its input graph")
        return original_fuse(expr)

    monkeypatch.setattr(dask_expr.Expr, "fuse", fuse_outside_input_graph)
    events: list[tuple] = []
    lock = threading.Lock()
    partition_calls = _PartitionCalls()

    counted = _frame().map_partitions(partition_calls, meta=PIECES[1])
    source = attach_lifecycle(counted, _recording_handlers("source", events, lock))
    filtered = attach_lifecycle(
        source[source["n"] > 1], _recording_handlers("filtered", events, lock)
    )

    with dask.config.set(scheduler=scheduler):
        _run(filtered, tmp_path, single_file=single_file)

    for name in ("source", "filtered"):
        kinds = [kind for owner, kind, _ in events if owner == name]
        assert (kinds.count("start"), kinds.count("end"), kinds.count("error")) == (1, 1, 0), name
        parts = sorted(n for owner, kind, n in events if owner == name and kind == "partition")
        assert parts == [0, 1, 2], name
    assert partition_calls.calls == {0: 1, 1: 1, 2: 1}
    assert _written(tmp_path) == _expected(
        [piece[piece["n"] > 1] for piece in PIECES], single_file=single_file
    )
