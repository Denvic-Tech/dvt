"""Наследование описаний по цепочке lineage: PASS/RENAME переносят, MERGE при совпадении."""

from __future__ import annotations

from collections.abc import Mapping

from ...entities import DatasetField
from ...lineage import LineageRef, ResolvedDescription
from ...types import LineageOp, LineageProvenance
from ..descriptions import effective_field_description
from .index import LineageIndex

_UNKNOWN = ResolvedDescription(text=None, provenance=LineageProvenance.UNKNOWN)
_DERIVED = ResolvedDescription(text=None, provenance=LineageProvenance.DERIVED)


class DescriptionResolver:
    def __init__(self, index: LineageIndex, fields: Mapping[str, DatasetField]) -> None:
        """fields: ключ `ds:<dataset_id>:<field_id>` → поле сущности."""
        self._index = index
        self._fields = fields
        self._memo: dict[str, ResolvedDescription] = {}

    def resolve(self, ref: LineageRef) -> ResolvedDescription:
        return self._resolve(ref, set())

    def _resolve(self, ref: LineageRef, visiting: set[str]) -> ResolvedDescription:
        cached = self._memo.get(ref.key)
        if cached is not None:
            return cached
        if ref.key in visiting:
            return _UNKNOWN
        visiting.add(ref.key)
        result = self._compute(ref, visiting)
        visiting.discard(ref.key)
        self._memo[ref.key] = result
        return result

    def _compute(self, ref: LineageRef, visiting: set[str]) -> ResolvedDescription:  # noqa: PLR0911
        if ref.is_dataset_field:
            field = self._fields.get(ref.key)
            if field is None:
                return _UNKNOWN
            text, provenance = effective_field_description(field)
            if text is None:
                return ResolvedDescription(text=None, provenance=LineageProvenance.UNKNOWN, source=ref)
            mapped = LineageProvenance.DECLARED if provenance.value == "declared" else LineageProvenance.SOURCE
            return ResolvedDescription(text=text, provenance=mapped, source=ref)

        found = self._index.column(ref)
        if found is None:
            return _UNKNOWN
        _, column = found
        if column.op in (LineageOp.PASS, LineageOp.RENAME, LineageOp.SOURCE):
            if len(column.deps) == 1 and not column.deps_unknown:
                parent = self._resolve(column.deps[0], visiting)
                if parent.text is None:
                    return ResolvedDescription(text=None, provenance=parent.provenance, source=parent.source)
                if column.op is LineageOp.SOURCE:
                    return parent
                return ResolvedDescription(text=parent.text, provenance=LineageProvenance.INHERITED, source=parent.source)
            return _UNKNOWN
        if column.op is LineageOp.MERGE:
            if column.deps_unknown or not column.deps:
                return _UNKNOWN
            parents = [self._resolve(dep, visiting) for dep in column.deps]
            texts = {parent.text for parent in parents}
            if len(texts) == 1 and parents[0].text is not None:
                return ResolvedDescription(text=parents[0].text, provenance=LineageProvenance.INHERITED, source=parents[0].source)
            return _DERIVED
        if column.op in (LineageOp.COMPUTE, LineageOp.AGGREGATE):
            return _DERIVED
        return _UNKNOWN
