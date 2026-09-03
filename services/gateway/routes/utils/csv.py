import csv
import io
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException

from services.gateway.deps import db_connection as db_connection_deps

from src.modules.db_connection import ConnectionRecord
from src.node_dsl.connection_types import FileConnectionRecord
from src.node_dsl.runtime.connections import resolve_file_fs_context

router = r = APIRouter(prefix="/csv", tags=["CSV Utilities"])


def _decode_delimiter(value: str | None) -> str:
    if not value:
        return ","

    try:
        return value.encode("utf-8").decode("unicode_escape")
    except Exception:
        return value


def _get_fs_and_path(db_connection: ConnectionRecord, path: str):
    try:
        fs_ctx = resolve_file_fs_context(FileConnectionRecord(db_connection), path=path)
    except TypeError as exc:
        raise HTTPException(
            status_code=400,
            detail="Unsupported storage type for CSV columns extraction",
        ) from exc
    return fs_ctx.fs, fs_ctx.path


def _path_has_glob(path: str) -> bool:
    return any(char in path for char in "*?[]")


def _is_csv_file(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() == ".csv"


def _resolve_csv_path(fs, path: str) -> str:
    if _path_has_glob(path):
        matches = sorted(
            candidate
            for candidate in fs.glob(path)
            if _is_csv_file(candidate) and not fs.isdir(candidate)
        )
        if not matches:
            raise HTTPException(
                status_code=404, detail="CSV file not found by the provided pattern"
            )
        return matches[0]

    if fs.isdir(path):
        entries = fs.ls(path, detail=True)
        files = sorted(
            entry["name"]
            for entry in entries
            if entry.get("type") == "file" and _is_csv_file(entry["name"])
        )
        if not files:
            raise HTTPException(
                status_code=404, detail="No CSV files found in the provided directory"
            )
        return files[0]

    if not fs.exists(path) or fs.isdir(path):
        raise HTTPException(status_code=404, detail="CSV file not found")

    return path


def _read_csv_header(fs, path: str, *, encoding: str | None, delimiter: str | None) -> list[str]:
    with (
        fs.open(path, "rb") as file_obj,
        io.TextIOWrapper(file_obj, encoding=encoding or "utf-8", newline="") as text_stream,
    ):
        reader = csv.reader(text_stream, delimiter=_decode_delimiter(delimiter))
        try:
            columns = next(reader)
        except StopIteration as exc:
            raise HTTPException(status_code=400, detail="CSV file is empty") from exc

    if columns:
        columns[0] = columns[0].lstrip("\ufeff")
    return columns


@r.post("/get-columns", response_model=list[str])
async def get_columns(
    db_connection: Annotated[
        ConnectionRecord, Depends(db_connection_deps.get_user_db_connection_by_body)
    ],
    path: Annotated[str, Body()],
    delimiter: Annotated[str | None, Body()] = ",",
    encoding: Annotated[str | None, Body()] = "utf-8",
) -> list[str]:
    fs, resolved_path = _get_fs_and_path(db_connection, path)
    csv_path = _resolve_csv_path(fs, resolved_path)
    return _read_csv_header(fs, csv_path, encoding=encoding, delimiter=delimiter)
