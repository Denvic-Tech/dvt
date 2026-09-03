from __future__ import annotations

import posixpath
from dataclasses import dataclass

from core.types import FsCtx

_OBJECT_STORAGE_PROTOCOLS = frozenset({"s3", "dvtfiles"})
_DIRECTORY_PROTOCOLS = frozenset({"file", "local", "ftp", "sftp", "smb"})


@dataclass(slots=True)
class ParquetFilesystem:
    ctx: FsCtx

    def __post_init__(self) -> None:
        if self.ctx.fs is None:
            import fsspec

            self.ctx.fs = fsspec.filesystem(self.ctx.protocol, **self.ctx.storage_options)

    @property
    def fs(self):
        return self.ctx.fs

    @property
    def target(self) -> str:
        return self.strip(self.ctx.path)

    def strip(self, path: str) -> str:
        strip_protocol = getattr(self.fs, "_strip_protocol", None)
        if callable(strip_protocol):
            return str(strip_protocol(path)).rstrip("/\\")
        return str(path).rstrip("/\\")

    def normalize(self, path: str) -> str:
        normalized = self.strip(str(path)).replace("\\", "/")
        normalized = posixpath.normpath(normalized)
        if self.ctx.protocol in {"file", "local"}:
            normalized = normalized.casefold()
        return normalized.rstrip("/")

    def paths_overlap(self, first: str, second: str) -> bool:
        """Return True when either path is the other path or its descendant."""

        left = self.normalize(first)
        right = self.normalize(second)
        if not left or not right:
            return False
        try:
            common = posixpath.commonpath([left, right])
        except ValueError:
            return False
        return common in (left, right)

    def assert_descendant(self, path: str, root: str) -> None:
        normalized_path = self.normalize(path)
        normalized_root = self.normalize(root)
        try:
            common = posixpath.commonpath([normalized_path, normalized_root])
        except ValueError as exc:
            raise ValueError(
                f"Generated Parquet path '{path}' escapes dataset root '{root}'."
            ) from exc
        if common != normalized_root or normalized_path == normalized_root:
            raise ValueError(
                f"Generated Parquet path '{path}' escapes dataset root '{root}'."
            )

    def exists(self, path: str) -> bool:
        return bool(self.fs.exists(path))

    def isdir(self, path: str) -> bool:
        try:
            return bool(self.fs.isdir(path))
        except (AttributeError, NotImplementedError):
            try:
                return self.fs.info(path).get("type") == "directory"
            except FileNotFoundError:
                return False

    def open(self, path: str, mode: str):
        return self.fs.open(path, mode)

    def ensure_parent(self, path: str) -> None:
        parent = posixpath.dirname(path.rstrip("/"))
        if not parent or self.ctx.protocol in _OBJECT_STORAGE_PROTOCOLS:
            return
        self.fs.makedirs(parent, exist_ok=True)

    def ensure_directory(self, path: str) -> None:
        if self.ctx.protocol in _OBJECT_STORAGE_PROTOCOLS:
            return
        self.fs.makedirs(path, exist_ok=True)

    def remove_file(self, path: str) -> None:
        try:
            if self.exists(path):
                self.fs.rm(path)
        except Exception:
            pass

    def remove_tree(self, path: str) -> None:
        self.fs.rm(path, recursive=True)

    def list_recursive(self, root: str) -> list[str]:
        root = root.rstrip("/")
        if not root:
            return []
        if self.exists(root) and not self.isdir(root):
            return [root]
        try:
            found = self.fs.find(root, withdirs=False)
        except TypeError:
            found = self.fs.find(root)
        except (AttributeError, NotImplementedError):
            found = []
            for current_root, _dirs, files in self.fs.walk(root):
                found.extend(posixpath.join(current_root, name) for name in files)
        if isinstance(found, dict):
            found = list(found)
        return sorted(str(path) for path in found)

    def list_parquet_files(self, root: str) -> list[str]:
        return [path for path in self.list_recursive(root) if path.lower().endswith(".parquet")]

    def is_non_empty_directory(self, root: str) -> bool:
        if self.exists(root) and not self.isdir(root):
            return True
        if self.ctx.protocol not in _DIRECTORY_PROTOCOLS:
            # Object stores expose inferred prefixes as directories. Only physical
            # objects count as contents so an existing virtual prefix is not a false positive.
            return bool(self.list_recursive(root))

        normalized_root = self.normalize(root)
        try:
            found = self.fs.find(root, withdirs=True)
            if isinstance(found, dict):
                found = list(found)
            return any(self.normalize(str(path)) != normalized_root for path in found)
        except TypeError:
            pass
        except (AttributeError, NotImplementedError):
            pass

        try:
            for current_root, dirs, files in self.fs.walk(root):
                current = self.normalize(str(current_root))
                if current != normalized_root or dirs or files:
                    return True
        except (AttributeError, NotImplementedError):
            return bool(self.list_recursive(root))
        else:
            return False

    def cleanup_empty_parents(self, paths: list[str], stop_at: str) -> None:
        if self.ctx.protocol in _OBJECT_STORAGE_PROTOCOLS:
            return
        stop_at = stop_at.rstrip("/")
        candidates = sorted(
            {posixpath.dirname(path) for path in paths},
            key=lambda value: value.count("/"),
            reverse=True,
        )
        for directory in candidates:
            current = directory
            while current and current != stop_at:
                try:
                    self.assert_descendant(current, stop_at)
                except ValueError:
                    break
                try:
                    if self.is_non_empty_directory(current):
                        break
                    self.fs.rmdir(current)
                except Exception:
                    break
                current = posixpath.dirname(current)
