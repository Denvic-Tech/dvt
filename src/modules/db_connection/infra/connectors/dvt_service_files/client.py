from __future__ import annotations

import io
import mimetypes
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.modules.file_storage.infra.db_models import DVTServiceFileObjectRecord


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalize_path(value: str | None) -> str:
    if value is None:
        return ""
    normalized = str(value).replace("\\", "/").strip("/")
    if not normalized:
        return ""
    parts = [part for part in normalized.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise ValueError("Path traversal is not allowed.")
    return "/".join(parts)


def _join_path(*parts: str | None) -> str:
    return "/".join(part for part in (_normalize_path(part) for part in parts) if part)


def _split_path(path: str) -> tuple[str, str]:
    normalized = _normalize_path(path)
    if not normalized:
        raise ValueError("Path does not reference a file.")
    if "/" not in normalized:
        return "", normalized
    parent, name = normalized.rsplit("/", 1)
    return parent, name


@dataclass(frozen=True, slots=True)
class DVTServiceFileEntry:
    name: str
    path: str
    is_dir: bool
    size: int = 0
    content_type: str | None = None
    sha256: str | None = None
    updated_at: datetime | None = None


class _ServiceFileHandle(io.BytesIO):
    def __init__(
        self,
        *,
        client: "DVTServiceFilesClient",
        full_path: str,
        mode: str,
        initial_bytes: bytes = b"",
        content_type: str | None = None,
    ) -> None:
        super().__init__(initial_bytes)
        self._client = client
        self._full_path = full_path
        self._mode = mode
        self._content_type = content_type
        self._closed_once = False
        if "a" in mode:
            self.seek(0, io.SEEK_END)

    def close(self) -> None:
        if not self._closed_once and any(flag in self._mode for flag in ("w", "a", "+")):
            self._client.write_file(
                self._full_path,
                self.getvalue(),
                content_type=self._content_type,
            )
        self._closed_once = True
        super().close()


class _OpenFileContext(AbstractContextManager[_ServiceFileHandle]):
    def __init__(self, handle: _ServiceFileHandle) -> None:
        self._handle = handle

    def __enter__(self) -> _ServiceFileHandle:
        return self._handle

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._handle.close()


class DVTServiceFilesClient:
    def __init__(
        self,
        *,
        engine: Engine,
        organization_id: str,
        project_id: str,
        root_prefix: str = "",
    ) -> None:
        self._engine = engine
        self.organization_id = organization_id
        self.project_id = project_id
        self.root_prefix = _normalize_path(root_prefix)

    def close(self) -> None:
        return None

    def _scoped_path(self, path: str | None = None, filename: str | None = None) -> str:
        return _join_path(self.root_prefix, path, filename)

    def _parent_and_name(self, path: str | None = None, filename: str | None = None) -> tuple[str, str]:
        return _split_path(self._scoped_path(path, filename))

    def _select_entry(self, parent_path: str, name: str):
        return sa.select(DVTServiceFileObjectRecord).where(
            DVTServiceFileObjectRecord.organization_id == self.organization_id,
            DVTServiceFileObjectRecord.project_id == self.project_id,
            DVTServiceFileObjectRecord.parent_path == parent_path,
            DVTServiceFileObjectRecord.name == name,
        )

    def _ensure_dir(self, connection, parent_path: str) -> None:
        current = ""
        for part in parent_path.split("/"):
            if not part:
                continue
            next_parent = current
            current = f"{current}/{part}" if current else part
            existing = connection.execute(self._select_entry(next_parent, part)).scalar_one_or_none()
            if existing is None:
                now = _utcnow()
                connection.execute(
                    sa.insert(DVTServiceFileObjectRecord).values(
                        id=str(uuid4()),
                        organization_id=self.organization_id,
                        project_id=self.project_id,
                        parent_path=next_parent,
                        name=part,
                        is_dir=True,
                        content=None,
                        content_type=None,
                        size=0,
                        sha256=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                continue
            if not existing.is_dir:
                raise NotADirectoryError(current)

    def mkdir(self, path: str | None = None, filename: str | None = None, *args, **kwargs) -> None:
        full_path = self._scoped_path(path, filename)
        if not full_path:
            return
        parent_path, name = _split_path(full_path)
        with Session(self._engine) as session, session.begin():
            self._ensure_dir(session, parent_path)
            existing = session.execute(self._select_entry(parent_path, name)).scalar_one_or_none()
            if existing is None:
                now = _utcnow()
                session.execute(
                    sa.insert(DVTServiceFileObjectRecord).values(
                        id=str(uuid4()),
                        organization_id=self.organization_id,
                        project_id=self.project_id,
                        parent_path=parent_path,
                        name=name,
                        is_dir=True,
                        content=None,
                        content_type=None,
                        size=0,
                        sha256=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
            elif not existing.is_dir:
                raise FileExistsError(full_path)

    def write_file(self, full_path: str, content: bytes, *, content_type: str | None = None) -> None:
        parent_path, name = _split_path(full_path)
        now = _utcnow()
        digest = sha256(content).hexdigest()
        media_type = content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        with Session(self._engine) as session, session.begin():
            self._ensure_dir(session, parent_path)
            existing = session.execute(self._select_entry(parent_path, name)).scalar_one_or_none()
            values = {
                "is_dir": False,
                "content": content,
                "content_type": media_type,
                "size": len(content),
                "sha256": digest,
                "updated_at": now,
            }
            if existing is None:
                session.execute(
                    sa.insert(DVTServiceFileObjectRecord).values(
                        id=str(uuid4()),
                        organization_id=self.organization_id,
                        project_id=self.project_id,
                        parent_path=parent_path,
                        name=name,
                        created_at=now,
                        **values,
                    )
                )
            else:
                session.execute(
                    sa.update(DVTServiceFileObjectRecord)
                    .where(DVTServiceFileObjectRecord.id == existing.id)
                    .values(**values)
                )

    def upload_file(
        self,
        *,
        path: str,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> None:
        self.write_file(self._scoped_path(path, filename), content, content_type=content_type)

    def _read_scoped_file(self, full_path: str) -> bytes:
        parent_path, name = _split_path(full_path)
        with Session(self._engine) as session:
            row = session.execute(self._select_entry(parent_path, name)).scalar_one_or_none()
            if row is None or row.is_dir:
                raise FileNotFoundError(full_path)
            return bytes(row.content or b"")

    def read_file(self, path: str) -> bytes:
        return self._read_scoped_file(self._scoped_path(path))

    def download_file(self, *, path: str, filename: str) -> tuple[str, bytes, str | None]:
        full_path = self._scoped_path(path, filename)
        parent_path, name = _split_path(full_path)
        with Session(self._engine) as session:
            row = session.execute(self._select_entry(parent_path, name)).scalar_one_or_none()
            if row is None or row.is_dir:
                raise FileNotFoundError(full_path)
            return row.name, bytes(row.content or b""), row.content_type

    def open_file(self, path: str | None = None, filename: str | None = None, *args, **kwargs):
        mode = kwargs.pop("mode", None)
        if mode is None and args:
            mode = args[0]
        mode = mode or "rb"
        full_path = self._scoped_path(path, filename)
        content_type = kwargs.pop("content_type", None)
        initial = b""
        if "r" in mode or "a" in mode:
            initial = self._read_scoped_file(full_path)
        handle = _ServiceFileHandle(
            client=self,
            full_path=full_path,
            mode=mode,
            initial_bytes=initial,
            content_type=content_type,
        )
        return _OpenFileContext(handle)

    def list_entries(self, path: str | None = None) -> list[DVTServiceFileEntry]:
        parent_path = self._scoped_path(path)
        with Session(self._engine) as session:
            rows = session.execute(
                sa.select(DVTServiceFileObjectRecord)
                .where(
                    DVTServiceFileObjectRecord.organization_id == self.organization_id,
                    DVTServiceFileObjectRecord.project_id == self.project_id,
                    DVTServiceFileObjectRecord.parent_path == parent_path,
                )
                .order_by(DVTServiceFileObjectRecord.is_dir.desc(), DVTServiceFileObjectRecord.name)
            ).scalars().all()
        return [
            DVTServiceFileEntry(
                name=row.name,
                path=_join_path(row.parent_path, row.name),
                is_dir=row.is_dir,
                size=row.size,
                content_type=row.content_type,
                sha256=row.sha256,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    def listdir(self, path: str | None = None) -> list[str]:
        return [entry.name for entry in self.list_entries(path)]

    def scandir(self, path: str | None = None):
        entries = []
        for entry in self.list_entries(path):
            entries.append(
                SimpleNamespace(
                    name=entry.name,
                    filename=entry.name,
                    path=entry.path,
                    is_dir=lambda entry=entry: entry.is_dir,
                    info=entry,
                )
            )
        return entries

    def info(self, path: str | None = None, filename: str | None = None) -> DVTServiceFileEntry:
        full_path = self._scoped_path(path, filename)
        if not full_path:
            return DVTServiceFileEntry(name="", path="", is_dir=True)
        parent_path, name = _split_path(full_path)
        with Session(self._engine) as session:
            row = session.execute(self._select_entry(parent_path, name)).scalar_one_or_none()
            if row is None:
                raise FileNotFoundError(full_path)
            return DVTServiceFileEntry(
                name=row.name,
                path=_join_path(row.parent_path, row.name),
                is_dir=row.is_dir,
                size=row.size,
                content_type=row.content_type,
                sha256=row.sha256,
                updated_at=row.updated_at,
            )

    def stat(self, path: str | None = None, filename: str | None = None):
        entry = self.info(path, filename)
        return SimpleNamespace(
            st_size=entry.size,
            size=entry.size,
            is_dir=entry.is_dir,
            name=entry.name,
            path=entry.path,
            updated_at=entry.updated_at,
        )

    def exists(self, path: str | None = None, filename: str | None = None) -> bool:
        try:
            self.info(path, filename)
            return True
        except FileNotFoundError:
            return False

    def remove(self, path: str | None = None, filename: str | None = None, *args, **kwargs) -> None:
        parent_path, name = self._parent_and_name(path, filename)
        with Session(self._engine) as session, session.begin():
            row = session.execute(self._select_entry(parent_path, name)).scalar_one_or_none()
            if row is None or row.is_dir:
                raise FileNotFoundError(self._scoped_path(path, filename))
            session.execute(sa.delete(DVTServiceFileObjectRecord).where(DVTServiceFileObjectRecord.id == row.id))

    def rmdir(self, path: str | None = None, filename: str | None = None, *args, **kwargs) -> None:
        parent_path, name = self._parent_and_name(path, filename)
        full_path = _join_path(parent_path, name)
        with Session(self._engine) as session, session.begin():
            child = session.execute(
                sa.select(DVTServiceFileObjectRecord.id).where(
                    DVTServiceFileObjectRecord.organization_id == self.organization_id,
                    DVTServiceFileObjectRecord.project_id == self.project_id,
                    DVTServiceFileObjectRecord.parent_path == full_path,
                ).limit(1)
            ).first()
            if child is not None:
                raise OSError("Directory is not empty.")
            row = session.execute(self._select_entry(parent_path, name)).scalar_one_or_none()
            if row is None or not row.is_dir:
                raise FileNotFoundError(full_path)
            session.execute(sa.delete(DVTServiceFileObjectRecord).where(DVTServiceFileObjectRecord.id == row.id))

    def rename(
        self,
        src_path: str | None = None,
        src_filename: str | None = None,
        dst_path: str | None = None,
        dst_filename: str | None = None,
        *args,
        **kwargs,
    ) -> None:
        src_parent, src_name = self._parent_and_name(src_path, src_filename)
        dst_parent, dst_name = self._parent_and_name(dst_path, dst_filename)
        src_full_path = _join_path(src_parent, src_name)
        dst_full_path = _join_path(dst_parent, dst_name)
        now = _utcnow()
        with Session(self._engine) as session, session.begin():
            self._ensure_dir(session, dst_parent)
            src = session.execute(self._select_entry(src_parent, src_name)).scalar_one_or_none()
            if src is None:
                raise FileNotFoundError(self._scoped_path(src_path, src_filename))
            existing = session.execute(self._select_entry(dst_parent, dst_name)).scalar_one_or_none()
            if existing is not None:
                raise FileExistsError(self._scoped_path(dst_path, dst_filename))
            session.execute(
                sa.update(DVTServiceFileObjectRecord)
                .where(DVTServiceFileObjectRecord.id == src.id)
                .values(parent_path=dst_parent, name=dst_name, updated_at=now)
            )
            if src.is_dir:
                children = session.execute(
                    sa.select(DVTServiceFileObjectRecord).where(
                        DVTServiceFileObjectRecord.organization_id == self.organization_id,
                        DVTServiceFileObjectRecord.project_id == self.project_id,
                        sa.or_(
                            DVTServiceFileObjectRecord.parent_path == src_full_path,
                            DVTServiceFileObjectRecord.parent_path.like(f"{src_full_path}/%"),
                        ),
                    )
                ).scalars()
                for child in children:
                    suffix = child.parent_path[len(src_full_path) :]
                    session.execute(
                        sa.update(DVTServiceFileObjectRecord)
                        .where(DVTServiceFileObjectRecord.id == child.id)
                        .values(parent_path=f"{dst_full_path}{suffix}", updated_at=now)
                    )

    def replace(self, *args, **kwargs) -> None:
        try:
            self.remove(path=kwargs.get("dst_path"), filename=kwargs.get("dst_filename"))
        except FileNotFoundError:
            pass
        self.rename(*args, **kwargs)
