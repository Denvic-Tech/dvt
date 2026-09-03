from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath

from core.parquet.write.models import ParquetWriteMode

DEFAULT_ADVANCED_TEMPLATE = "<increment>.parquet"
_TOKEN_RE = re.compile(r"<([a-zA-Z_][a-zA-Z0-9_]*)>")
_UUID_RE = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"


@dataclass(frozen=True, slots=True)
class NamingContext:
    partition_index: int
    increment: int


class IncrementAllocator:
    def __init__(self, start: int = 0) -> None:
        self._value = int(start)
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            value = self._value
            self._value += 1
            return value


class FilenameTemplate:
    _KNOWN_TOKENS = frozenset({"partition_index", "increment", "uuid"})

    def __init__(self, raw_template: str | None) -> None:
        resolved_template = (
            DEFAULT_ADVANCED_TEMPLATE if raw_template is None else raw_template
        )
        self.template = normalize_filename_template(resolved_template)
        self.tokens = frozenset(_TOKEN_RE.findall(self.template))
        unknown = sorted(self.tokens - self._KNOWN_TOKENS)
        if unknown:
            raise ValueError(f"Unknown Parquet filename token(s): {unknown}.")
        self._validate_filename_only()
        self._matcher = self._compile_matcher()

    @property
    def has_increment(self) -> bool:
        return "increment" in self.tokens

    @property
    def has_uuid(self) -> bool:
        return "uuid" in self.tokens

    @property
    def has_partition_index(self) -> bool:
        return "partition_index" in self.tokens

    @property
    def has_globally_unique_token(self) -> bool:
        return self.has_increment or self.has_uuid

    def validate_uniqueness(
        self,
        *,
        mode: ParquetWriteMode,
        source_partitions: int,
        row_cap: int | None,
        partition_on: tuple[str, ...],
    ) -> None:
        if self.has_globally_unique_token:
            return

        if mode is ParquetWriteMode.APPEND:
            raise ValueError(
                "Filename template is unsafe for append and may collide with existing files. "
                "Add <increment> or <uuid>."
            )

        if self.has_partition_index:
            if row_cap is not None or partition_on:
                raise ValueError(
                    "Filename template may generate duplicate files because one Dask partition can "
                    "produce multiple output files. Add <increment> or <uuid>."
                )
            return

        if source_partitions > 1 or row_cap is not None or partition_on:
            raise ValueError(
                "Filename template may generate duplicate physical Parquet files. "
                "Add <increment> or <uuid>."
            )

    def render(self, context: NamingContext) -> str:
        replacements = {
            "partition_index": f"{context.partition_index:05d}",
            "increment": f"{context.increment:05d}",
            "uuid": str(uuid.uuid4()),
        }

        filename = _TOKEN_RE.sub(lambda match: replacements[match.group(1)], self.template)
        validate_physical_filename(filename)
        return filename

    def extract_increment(self, filename: str) -> int | None:
        if not self.has_increment:
            return None
        match = self._matcher.fullmatch(filename)
        if match is None:
            return None
        value = match.groupdict().get("increment")
        return int(value) if value is not None else None

    def matches(self, filename: str) -> bool:
        return self._matcher.fullmatch(filename) is not None

    def _validate_filename_only(self) -> None:
        if not self.template.strip():
            raise ValueError("Parquet filename template cannot be empty.")
        if "\x00" in self.template:
            raise ValueError("Parquet filename template cannot contain NUL.")
        if "/" in self.template or "\\" in self.template:
            raise ValueError(
                "Parquet filename template must contain a filename only; directory separators are forbidden."
            )
        if self.template in {".", ".."}:
            raise ValueError("Parquet filename template cannot be '.' or '..'.")
        if PurePosixPath(self.template).is_absolute():
            raise ValueError("Parquet filename template cannot be an absolute path.")

    def _compile_matcher(self) -> re.Pattern[str]:
        cursor = 0
        parts: list[str] = []
        seen_named_groups: set[str] = set()
        for match in _TOKEN_RE.finditer(self.template):
            parts.append(re.escape(self.template[cursor : match.start()]))
            token = match.group(1)
            if token in {"increment", "partition_index"}:
                pattern = r"\d+"
            elif token == "uuid":
                pattern = _UUID_RE
            else:  # guarded by __init__
                raise AssertionError(token)

            if token in seen_named_groups:
                parts.append(f"(?:{pattern})")
            else:
                parts.append(f"(?P<{token}>{pattern})")
                seen_named_groups.add(token)
            cursor = match.end()
        parts.append(re.escape(self.template[cursor:]))
        return re.compile("".join(parts), re.IGNORECASE)


def normalize_filename_template(template: str) -> str:
    normalized = (template or "").strip()
    if not normalized:
        raise ValueError("Parquet filename template cannot be empty.")
    if not normalized.lower().endswith(".parquet"):
        normalized = f"{normalized}.parquet"
    return normalized


def validate_physical_filename(filename: str) -> None:
    if not filename or filename in {".", ".."}:
        raise ValueError("Generated Parquet filename is invalid.")
    if "\x00" in filename or "/" in filename or "\\" in filename:
        raise ValueError("Generated Parquet filename must not contain path separators or NUL.")
    if not filename.lower().endswith(".parquet"):
        raise ValueError("Generated Parquet filename must end with '.parquet'.")
