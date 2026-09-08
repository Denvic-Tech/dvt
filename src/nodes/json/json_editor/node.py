from dataclasses import dataclass, field
from typing import Any

from core.metadata import get_json_metadata
from core.metadata.json_tabular import normalize_tabular_json
from core.metadata.json_utils import (
    JSON_ARRAY_ITEM_TOKEN,
    build_display_json_path,
    is_absolute_json_path,
    is_json_path_prefix,
    json_safe,
    parse_json_path,
    relative_json_path,
    resolve_json_path,
    tokens_to_output_key,
)
from core.types import JSONFlattenCandidateKind, JSONMetadata

from src.logger import logger
from src.node_dsl import IO, InputField, JSONOutputBaseNode, OutputField


MISSING = object()


@dataclass(frozen=True, slots=True)
class _MetaPathSpec:
    absolute_tokens: tuple[str, ...]
    resolve_from_record: bool
    resolve_tokens: tuple[str, ...]
    output_tokens: tuple[str, ...]


@dataclass(slots=True)
class _EditorContext:
    separator: str
    record_scope_tokens: tuple[str, ...]
    keep_paths: set[tuple[str, ...]]
    explode_paths: set[tuple[str, ...]]
    exclude_paths: tuple[tuple[str, ...], ...]
    max_rows: int
    produced_rows: int = 0
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)

    def remaining_capacity(self) -> int:
        return max(0, self.max_rows - self.produced_rows)

    def mark_truncated(self, message: str) -> None:
        self.truncated = True
        if message not in self.warnings:
            self.warnings.append(message)

    def is_excluded(self, absolute_tokens: tuple[str, ...]) -> bool:
        return any(is_json_path_prefix(prefix, absolute_tokens) for prefix in self.exclude_paths)

    def should_keep_json(self, absolute_tokens: tuple[str, ...]) -> bool:
        return absolute_tokens in self.keep_paths and not self.is_excluded(absolute_tokens)

    def should_explode(self, absolute_tokens: tuple[str, ...]) -> bool:
        return absolute_tokens in self.explode_paths and not self.is_excluded(absolute_tokens)


class JSONEditor(JSONOutputBaseNode):
    TITLE = "JSON Editor"
    EMOJI = "🧰"
    CATEGORY = "JSON"
    DESCRIPTION = "Подготовка JSON к дальнейшей нормализации и преобразованию в DataFrame."

    json: IO.JSON = InputField(multiline=True)
    record_path: str = InputField(default="", description="Путь к источнику записей.")
    meta_paths: list[str] = InputField(default=[], description="Пути, которые нужно добавить в каждую запись.")
    explode_paths: list[str] = InputField(default=[], description="Массивы, по которым нужно размножать строки.")
    keep_json_paths: list[str] = InputField(default=[], description="Поддеревья, которые нужно сохранить как JSON.")
    exclude_paths: list[str] = InputField(default=[], description="Пути, которые нужно исключить из результата.")
    separator: str = InputField(default=".", description="Разделитель для итоговых flat keys.")
    auto_detect_record_path: bool = InputField(
        default=True,
        description="Автоматически подобрать record_path из JSON metadata.",
    )
    max_rows: int = InputField(
        default=10000,
        min_value=1,
        max_value=100000,
        description="Максимальное число выходных строк.",
    )

    output: IO.JSON = OutputField()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.stats = {
            "effective_record_path": "$",
            "rows_truncated": False,
            "produced_rows": 0,
            "max_rows": None,
            "detected_matrix": False,
            "matrix_header_mode": "disabled",
            "matrix_columns": [],
            "detected_matrices": [],
            "warnings": [],
        }

    def process(self) -> list[dict[str, Any]]:
        normalized = normalize_tabular_json(self.json)
        document = normalized.value
        metadata = get_json_metadata(document)
        effective_record_tokens = self._resolve_record_path_tokens(document, metadata)
        record_source = resolve_json_path(document, effective_record_tokens, missing=MISSING)
        effective_record_path = build_display_json_path(effective_record_tokens)
        matrix_infos = [
            {
                "path": build_display_json_path(matrix.path_tokens),
                "header_mode": matrix.header_mode,
                "columns": list(matrix.columns),
                "row_count": matrix.row_count,
            }
            for matrix in normalized.matrices
        ]
        matrix_warnings = [
            warning
            for matrix in normalized.matrices
            for warning in matrix.warnings
        ]

        if record_source is MISSING:
            warning = f"JSON Editor record_path not found: {effective_record_path}"
            logger.warning(warning)
            self.output = []
            self.stats = {
                "effective_record_path": effective_record_path,
                "rows_truncated": False,
                "produced_rows": 0,
                "max_rows": self.max_rows,
                "detected_matrix": bool(normalized.matrices),
                "matrix_header_mode": (
                    normalized.matrices[0].header_mode if normalized.matrices else "disabled"
                ),
                "matrix_columns": list(normalized.matrices[0].columns) if normalized.matrices else [],
                "detected_matrices": matrix_infos,
                "warnings": [*matrix_warnings, warning],
            }
            return self.output

        if isinstance(record_source, list):
            base_records = record_source
            record_scope_tokens = effective_record_tokens + (JSON_ARRAY_ITEM_TOKEN,)
        else:
            base_records = [record_source]
            record_scope_tokens = effective_record_tokens

        context = _EditorContext(
            separator=self.separator,
            record_scope_tokens=record_scope_tokens,
            keep_paths={self._normalize_config_path(path, record_scope_tokens) for path in self.keep_json_paths},
            explode_paths={self._normalize_config_path(path, record_scope_tokens) for path in self.explode_paths},
            exclude_paths=tuple(
                self._normalize_config_path(path, record_scope_tokens)
                for path in self.exclude_paths
            ),
            max_rows=int(self.max_rows),
            warnings=matrix_warnings[:],
        )
        meta_specs = [
            self._build_meta_path_spec(path, record_scope_tokens)
            for path in self.meta_paths
        ]

        rows: list[dict[str, Any]] = []
        for record in base_records:
            if context.remaining_capacity() <= 0:
                context.mark_truncated("JSON Editor output was truncated by max_rows.")
                break

            fragments = _flatten_record_value(
                value=record,
                absolute_tokens=record_scope_tokens,
                relative_tokens=(),
                context=context,
            )
            if not fragments:
                fragments = [{}]

            meta_values = self._build_meta_values(
                document=document,
                record=record,
                meta_specs=meta_specs,
                context=context,
            )
            for fragment in fragments:
                if context.produced_rows >= context.max_rows:
                    context.mark_truncated("JSON Editor output was truncated by max_rows.")
                    break
                row = dict(fragment)
                row.update(meta_values)
                rows.append(row)
                context.produced_rows += 1

        if context.truncated:
            logger.warning(
                "JSON Editor truncated output at {} rows for record_path {}",
                context.max_rows,
                effective_record_path,
            )
        for warning in context.warnings:
            logger.warning(warning)

        self.output = rows
        self.stats = {
            "effective_record_path": effective_record_path,
            "rows_truncated": context.truncated,
            "produced_rows": len(rows),
            "max_rows": context.max_rows,
            "detected_matrix": bool(normalized.matrices),
            "matrix_header_mode": (
                normalized.matrices[0].header_mode if normalized.matrices else "disabled"
            ),
            "matrix_columns": list(normalized.matrices[0].columns) if normalized.matrices else [],
            "detected_matrices": matrix_infos,
            "warnings": context.warnings[:],
        }
        return self.output

    async def process_metadata(self) -> None:
        self.process()

    def infer_metadata(self):
        if self.output is not ...:
            return {"output": get_json_metadata(self.output)}
        self.process()
        return {"output": get_json_metadata(self.output)}

    def _resolve_record_path_tokens(self, document: Any, metadata: JSONMetadata) -> tuple[str, ...]:
        if self.record_path and str(self.record_path).strip():
            return parse_json_path(self.record_path)

        if self.auto_detect_record_path:
            record_candidates = [
                candidate
                for candidate in metadata.flatten_candidates
                if candidate.kind == JSONFlattenCandidateKind.RECORD_PATH and candidate.confidence >= 0.9
            ]
            if record_candidates:
                return parse_json_path(record_candidates[0].path)

        if isinstance(document, list):
            return ()

        return ()

    def _normalize_config_path(
        self,
        path: str,
        record_scope_tokens: tuple[str, ...],
    ) -> tuple[str, ...]:
        tokens = parse_json_path(path)
        if is_absolute_json_path(path):
            return tokens
        return record_scope_tokens + tokens

    def _build_meta_path_spec(
        self,
        path: str,
        record_scope_tokens: tuple[str, ...],
    ) -> _MetaPathSpec:
        raw_tokens = parse_json_path(path)
        if not is_absolute_json_path(path):
            return _MetaPathSpec(
                absolute_tokens=record_scope_tokens + raw_tokens,
                resolve_from_record=True,
                resolve_tokens=raw_tokens,
                output_tokens=raw_tokens,
            )

        relative_tokens = relative_json_path(raw_tokens, record_scope_tokens)
        if relative_tokens is not None:
            return _MetaPathSpec(
                absolute_tokens=raw_tokens,
                resolve_from_record=True,
                resolve_tokens=relative_tokens,
                output_tokens=relative_tokens,
            )

        return _MetaPathSpec(
            absolute_tokens=raw_tokens,
            resolve_from_record=False,
            resolve_tokens=raw_tokens,
            output_tokens=raw_tokens,
        )

    def _build_meta_values(
        self,
        *,
        document: Any,
        record: Any,
        meta_specs: list[_MetaPathSpec],
        context: _EditorContext,
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for spec in meta_specs:
            if context.is_excluded(spec.absolute_tokens):
                continue

            source = record if spec.resolve_from_record else document
            resolved = resolve_json_path(source, spec.resolve_tokens, missing=MISSING)
            output_key = tokens_to_output_key(spec.output_tokens, separator=context.separator)
            values[output_key] = None if resolved is MISSING else json_safe(resolved)
        return values


def _flatten_record_value(
    *,
    value: Any,
    absolute_tokens: tuple[str, ...],
    relative_tokens: tuple[str, ...],
    context: _EditorContext,
) -> list[dict[str, Any]]:
    if context.is_excluded(absolute_tokens):
        return [{}]

    if context.should_keep_json(absolute_tokens):
        key = tokens_to_output_key(relative_tokens, separator=context.separator)
        return [{key: json_safe(value)}]

    if isinstance(value, dict):
        fragments: list[dict[str, Any]] = [{}]
        for key, item in value.items():
            child_absolute = absolute_tokens + (str(key),)
            if context.is_excluded(child_absolute):
                continue
            child_relative = relative_tokens + (str(key),)
            child_fragments = _flatten_record_value(
                value=item,
                absolute_tokens=child_absolute,
                relative_tokens=child_relative,
                context=context,
            )
            fragments = _cross_merge_rows(fragments, child_fragments, context)
            if not fragments:
                break
        return fragments or [{}]

    if isinstance(value, list):
        key = tokens_to_output_key(relative_tokens, separator=context.separator)
        if context.should_explode(absolute_tokens):
            if not value:
                return [{key: None}]

            fragments: list[dict[str, Any]] = []
            for item in value:
                if len(fragments) >= context.remaining_capacity():
                    context.mark_truncated("JSON Editor output was truncated by max_rows.")
                    break

                child_absolute = absolute_tokens + (JSON_ARRAY_ITEM_TOKEN,)
                if isinstance(item, dict):
                    item_fragments = _flatten_record_value(
                        value=item,
                        absolute_tokens=child_absolute,
                        relative_tokens=relative_tokens,
                        context=context,
                    )
                elif isinstance(item, list):
                    item_fragments = _flatten_record_value(
                        value=item,
                        absolute_tokens=child_absolute,
                        relative_tokens=relative_tokens,
                        context=context,
                    )
                else:
                    item_fragments = [{key: json_safe(item)}]

                for fragment in item_fragments:
                    if len(fragments) >= context.remaining_capacity():
                        context.mark_truncated("JSON Editor output was truncated by max_rows.")
                        break
                    fragments.append(fragment)

            return fragments or [{key: None}]

        return [{key: json_safe(value)}]

    key = tokens_to_output_key(relative_tokens, separator=context.separator)
    return [{key: json_safe(value)}]


def _cross_merge_rows(
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    context: _EditorContext,
) -> list[dict[str, Any]]:
    if not left_rows:
        return right_rows[:context.remaining_capacity()]
    if not right_rows:
        return left_rows[:context.remaining_capacity()]

    merged: list[dict[str, Any]] = []
    capacity = context.remaining_capacity()
    for left in left_rows:
        for right in right_rows:
            if len(merged) >= capacity:
                context.mark_truncated("JSON Editor output was truncated by max_rows.")
                return merged
            merged.append({**left, **right})
    return merged
