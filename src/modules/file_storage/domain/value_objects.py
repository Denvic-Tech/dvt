from __future__ import annotations

from dataclasses import dataclass

from .exceptions import InvalidStorageEntryNameError, InvalidStoragePathError


def _normalize_slashes(value: str) -> str:
    return value.replace("\\", "/")


@dataclass(frozen=True, slots=True)
class StorageRelativePath:
    value: str = ""

    @classmethod
    def from_raw(cls, raw: str | None) -> "StorageRelativePath":
        source = _normalize_slashes((raw or "").strip())
        if source in {"", "/"}:
            return cls("")

        parts: list[str] = []
        for part in source.split("/"):
            if not part or part == ".":
                continue
            if part == "..":
                raise InvalidStoragePathError(raw or "", "path traversal is not allowed")
            parts.append(part)
        return cls("/".join(parts))

    def join(self, *parts: str) -> "StorageRelativePath":
        joined = self.value
        for part in parts:
            entry_name = StorageEntryName.from_raw(part)
            joined = "/".join(segment for segment in [joined, entry_name.value] if segment)
        return StorageRelativePath(joined)

    @property
    def name(self) -> str:
        if self.is_root:
            raise InvalidStoragePathError(self.value, "root path does not have a name")
        return self.value.rsplit("/", 1)[-1]

    @property
    def parent(self) -> "StorageRelativePath":
        if self.is_root:
            raise InvalidStoragePathError(self.value, "root path does not have a parent")
        if "/" not in self.value:
            return StorageRelativePath("")
        return StorageRelativePath(self.value.rsplit("/", 1)[0])

    def with_name(self, raw_name: str) -> "StorageRelativePath":
        return self.parent.join(raw_name)

    def move_to(self, target_parent_raw: str | None) -> "StorageRelativePath":
        return StorageRelativePath.from_raw(target_parent_raw).join(self.name)

    @property
    def is_root(self) -> bool:
        return self.value == ""

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class StorageEntryName:
    value: str

    @classmethod
    def from_raw(cls, raw: str | None) -> "StorageEntryName":
        value = _normalize_slashes((raw or "").strip())
        if not value:
            raise InvalidStorageEntryNameError(raw or "", "name cannot be empty")
        if "/" in value:
            raise InvalidStorageEntryNameError(value, "name cannot contain path separators")
        if value in {".", ".."}:
            raise InvalidStorageEntryNameError(value, "reserved path segment")
        return cls(value)

    def __str__(self) -> str:
        return self.value
