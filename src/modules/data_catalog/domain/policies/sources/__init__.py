"""Реестр адаптеров видов источников. Новый вид = новый адаптер, остальной каталог не меняется."""

from __future__ import annotations

from collections.abc import Iterable

from ...catalog_values import DatasetLocator
from ...exceptions import UnknownSourceKindError
from .contracts import ResolvedLocator, ResolvedLocators, SourceCandidate, SourceKindAdapter
from .db_table import DbTableAdapter


class SourceKindRegistry:
    def __init__(self, adapters: Iterable[SourceKindAdapter]) -> None:
        self._adapters: dict[str, SourceKindAdapter] = {}
        for adapter in adapters:
            if adapter.kind in self._adapters:
                raise ValueError(f"duplicate source kind adapter: {adapter.kind!r}")
            self._adapters[adapter.kind] = adapter

    def adapters(self) -> tuple[SourceKindAdapter, ...]:
        return tuple(self._adapters.values())

    def kinds(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    def get(self, kind: str) -> SourceKindAdapter:
        adapter = self._adapters.get(kind)
        if adapter is None:
            raise UnknownSourceKindError(f"No source adapter is registered for kind {kind!r}")
        return adapter

    def build_key(self, locator: DatasetLocator) -> str:
        return self.get(locator.kind).build_key(locator)

    def describe(self, locator: DatasetLocator) -> str:
        return self.get(locator.kind).describe(locator)


def default_registry() -> SourceKindRegistry:
    return SourceKindRegistry((DbTableAdapter(),))


__all__ = [
    "ResolvedLocator",
    "ResolvedLocators",
    "SourceCandidate",
    "SourceKindAdapter",
    "SourceKindRegistry",
    "default_registry",
]
