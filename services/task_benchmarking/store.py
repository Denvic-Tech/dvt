"""Partition files of the stage barrier emulated by BenchmarkStoreWrite and BenchmarkStoreRead.

One file per dask partition, named ``part-<number>`` in the partition order. ``parquet`` and
``arrow_ipc`` drop the index; ``dvt_codec`` stores the bytes that the product's pipeline cache
puts into Valkey for one partition (``DumpEngineCodec``: msgpack around Feather with lz4).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

FORMATS = ("parquet", "arrow_ipc", "dvt_codec")
_SUFFIXES = {"parquet": ".parquet", "arrow_ipc": ".arrow", "dvt_codec": ".dvt"}


@lru_cache(maxsize=1)
def _dvt_codec() -> Any:
    from src.modules.pipeline_cache import DumpEngineCodec

    return DumpEngineCodec()


def _suffix(fmt: str) -> str:
    try:
        return _SUFFIXES[fmt]
    except KeyError:
        raise ValueError(f"Unknown store format {fmt!r}; expected one of {FORMATS}") from None


def partition_path(root: Path, fmt: str, number: int) -> Path:
    return root / f"part-{number:05d}{_suffix(fmt)}"


def partition_files(root: Path, fmt: str) -> list[Path]:
    return sorted(root.glob(f"part-*{_suffix(fmt)}"))


def clear_partitions(root: Path) -> None:
    """Delete partition files of every format in ``root``; other files are left alone."""
    for suffix in _SUFFIXES.values():
        for path in root.glob(f"part-*{suffix}"):
            path.unlink()


def write_partition(pdf: pd.DataFrame, path: Path, fmt: str, compression: str | None) -> int:
    """Write one partition and return the file size in bytes.

    ``compression`` None means the format default: snappy for parquet, none for arrow_ipc.
    ``dvt_codec`` always uses the product codec settings.
    """
    if fmt == "dvt_codec":
        path.write_bytes(_dvt_codec().dump(pdf))
        return path.stat().st_size
    table = pa.Table.from_pandas(pdf, preserve_index=False)
    if fmt == "parquet":
        pq.write_table(table, path, compression=compression or "snappy")
    elif fmt == "arrow_ipc":
        codec = None if compression in (None, "none") else compression
        options = pa.ipc.IpcWriteOptions(compression=codec)
        with (
            pa.OSFile(str(path), "wb") as sink,
            pa.ipc.new_file(sink, table.schema, options=options) as writer,
        ):
            writer.write_table(table)
    else:
        _suffix(fmt)
    return path.stat().st_size


def read_partition(path: str | Path, fmt: str) -> pd.DataFrame:
    if fmt == "dvt_codec":
        return _dvt_codec().load(Path(path).read_bytes())
    if fmt == "parquet":
        return pq.read_table(path).to_pandas()
    if fmt == "arrow_ipc":
        return pa.ipc.open_file(pa.memory_map(str(path), "r")).read_all().to_pandas()
    raise ValueError(f"Unknown store format {fmt!r}; expected one of {FORMATS}")
