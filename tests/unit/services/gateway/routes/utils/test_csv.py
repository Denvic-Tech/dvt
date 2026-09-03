from __future__ import annotations

import fsspec
import pytest
from fastapi import HTTPException

from services.gateway.routes.utils import csv as csv_utils


def test_resolve_csv_path_returns_first_csv_from_directory(tmp_path) -> None:
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    (batch_dir / "b.csv").write_text("id,name\n1,John\n", encoding="utf-8")
    (batch_dir / "a.csv").write_text("id,name\n2,Jane\n", encoding="utf-8")
    (batch_dir / "notes.txt").write_text("ignore", encoding="utf-8")

    fs = fsspec.filesystem("file")

    resolved = csv_utils._resolve_csv_path(fs, batch_dir.as_posix())

    assert resolved.endswith("/a.csv")


def test_read_csv_header_supports_escaped_delimiter(tmp_path) -> None:
    file_path = tmp_path / "data.csv"
    file_path.write_text("id\tname\tvalue\n1\tAlice\t10\n", encoding="utf-8")

    fs = fsspec.filesystem("file")

    columns = csv_utils._read_csv_header(
        fs,
        file_path.as_posix(),
        encoding="utf-8",
        delimiter="\\t",
    )

    assert columns == ["id", "name", "value"]


def test_resolve_csv_path_raises_when_directory_has_no_csv(tmp_path) -> None:
    empty_dir = tmp_path / "batch"
    empty_dir.mkdir()
    (empty_dir / "data.txt").write_text("id,name\n", encoding="utf-8")

    fs = fsspec.filesystem("file")

    with pytest.raises(HTTPException) as exc_info:
        csv_utils._resolve_csv_path(fs, empty_dir.as_posix())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "No CSV files found in the provided directory"
