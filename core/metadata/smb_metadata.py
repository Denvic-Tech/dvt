from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import fsspec
from cachetools import TTLCache, cached

from core.types import SMBDirectoryMetadata, SMBFile, SMBFolder, SMBNode
from core.types.metadata import SMBMetadata

smb_metadata_cache = TTLCache(maxsize=100, ttl=2)
smb_path_metadata_cache = TTLCache(maxsize=500, ttl=2)


def _make_connection_string(
    host: str,
    port: int,
    share: str,
    username: str | None,
) -> str:
    user_part = f"{username}@" if username else ""
    return f"smb://{user_part}{host}:{port}/{share}"


def _make_connection_prefix(host: str, port: int, share: str) -> str:
    return f"{host}:{port}/{share}"


def _normalize_relative_path(path: str) -> str:
    normalized = path.strip().strip("/")
    return normalized


def _build_share_path(share: str, path: str = "") -> str:
    normalized_share = _normalize_relative_path(share)
    normalized_path = _normalize_relative_path(path)
    if not normalized_path:
        return f"/{normalized_share}"
    return f"/{normalized_share}/{normalized_path}"


def _to_relative_share_path(entry_name: str, share: str) -> str:
    normalized = entry_name.replace("\\", "/").lstrip("/")
    share_prefix = _normalize_relative_path(share)
    if normalized == share_prefix:
        return ""
    if normalized.startswith(f"{share_prefix}/"):
        return normalized[len(share_prefix) + 1 :]
    return normalized


def _to_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    return None


@cached(cache=smb_metadata_cache)
def load_smb_metadata(
    *,
    connection_id: str,
    host: str,
    port: int,
    share: str,
    username: str | None,
    password: str,
    max_items: int = 100,
) -> SMBMetadata:
    nodes, _, _ = load_smb_path_metadata(
        host=host,
        port=port,
        share=share,
        username=username,
        password=password,
        path="",
        max_items=max_items,
    )

    total_size = sum(node.size for node in nodes if isinstance(node, SMBFile))
    files_count = sum(1 for node in nodes if isinstance(node, SMBFile))
    folders_count = sum(1 for node in nodes if isinstance(node, SMBFolder))

    return SMBMetadata(
        connection_id=connection_id,
        connection_string=_make_connection_string(host=host, port=port, share=share, username=username),
        connection_prefix=_make_connection_prefix(host=host, port=port, share=share),
        host=host,
        port=port,
        share=share,
        username=username,
        initial_directory="/",
        directory=SMBDirectoryMetadata(
            host=host,
            share=share,
            current_path="/",
            nodes=nodes,
            total_size=total_size,
            files_count=files_count,
            folders_count=folders_count,
        ),
    )


@cached(cache=smb_path_metadata_cache)
def load_smb_path_metadata(
    *,
    host: str,
    port: int,
    share: str,
    username: str | None,
    password: str,
    path: str = "",
    max_items: int = 1000,
) -> tuple[list[SMBNode], bool, str | None]:
    fs = fsspec.filesystem(
        "smb",
        host=host,
        port=port,
        username=username,
        password=password,
    )
    share_path = _build_share_path(share=share, path=path)

    try:
        entries = list(fs.ls(share_path, detail=True))
    except Exception:
        return [], False, None

    nodes: list[SMBNode] = []
    for entry in entries[:max_items]:
        relative_path = _to_relative_share_path(str(entry.get("name", "")), share=share)
        if not relative_path:
            continue

        name = relative_path.rstrip("/").split("/")[-1]
        if not name:
            continue

        entry_type = str(entry.get("type", "file")).lower()
        if entry_type == "directory":
            nodes.append(
                SMBFolder(
                    name=name,
                    path=relative_path.rstrip("/"),
                    permissions=None,
                )
            )
            continue

        nodes.append(
            SMBFile(
                name=name,
                path=relative_path,
                size=int(entry.get("size", 0) or 0),
                last_modified=_to_datetime(entry.get("mtime")),
                permissions=None,
            )
        )

    is_truncated = len(entries) > max_items
    return nodes, is_truncated, None
