"""Bounded context Data Catalog.

Пакет импортирует только домен: `src.node_dsl.type_resolver` зависит от `TableSchema`, а
инфраструктура каталога, в свою очередь, зависит от `pipeline_graph` и `node_dsl`. Эагерный
импорт facade/infra здесь замыкал бы цикл, поэтому тяжёлые имена отдаются лениво.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .domain import ColumnSchema, TableSchema

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "BuildSchema": (".flow", "BuildSchema"),
    "DataCatalogUseCases": (".facade", "DataCatalogUseCases"),
    "DataFrameSchemaMapping": (".infra", "DataFrameSchemaMapping"),
    "build_data_catalog_use_cases": (".facade", "build_data_catalog_use_cases"),
    "build_table_schema_from_dataframe": (".facade", "build_table_schema_from_dataframe"),
    "on_project_variables_changed": (".facade", "on_project_variables_changed"),
    "rebuild_project_catalog_projection": (".facade", "rebuild_project_catalog_projection"),
    "record_observed_node_metadata": (".facade", "record_observed_node_metadata"),
}

__all__ = [
    "BuildSchema",
    "ColumnSchema",
    "DataCatalogUseCases",
    "DataFrameSchemaMapping",
    "TableSchema",
    "build_data_catalog_use_cases",
    "build_table_schema_from_dataframe",
    "on_project_variables_changed",
    "rebuild_project_catalog_projection",
    "record_observed_node_metadata",
]


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
