"""Инфраструктура Data Catalog.

Пакет отдаёт имена лениво: ORM-модели из `db_models` импортируют Alembic, фикстуры и
`crud.project.delete`, которые живут в сервисах без доступа к тяжёлым зависимостям гейтвеев
(sqlglot, `core.db.ddl`, `db_catalog` и через них `botocore`). Эагерный импорт гейтвеев здесь
протаскивал бы эти зависимости в Project Scheduler.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, str] = {
    "DataCatalogInfraError": ".exceptions",
    "DataCatalogPersistenceError": ".exceptions",
    "DataFrameSchemaMappingError": ".exceptions",
    "DbCatalogDatasetSchemaSource": ".gateways",
    "NodeDslExpressionResolver": ".gateways",
    "SQLAlchemyCatalogProjectSource": ".gateways",
    "SQLAlchemyProjectGraphGateway": ".gateways",
    "SQLConnectionLocatorGateway": ".gateways",
    "SqlglotTableReferenceExtractor": ".gateways",
    "to_graph_input_value": ".gateways",
    "DataFrameSchemaMapper": ".mappers",
    "DataFrameSchemaMapping": ".mappers",
    "build_observation": ".observers",
    "SQLAlchemyDatasetConnectionRepository": ".repositories",
    "SQLAlchemyDatasetFieldRepository": ".repositories",
    "SQLAlchemyDatasetLinkRepository": ".repositories",
    "SQLAlchemyDatasetRepository": ".repositories",
    "SQLAlchemyProjectionRepository": ".repositories",
}

__all__ = [
    "DataCatalogInfraError",
    "DataCatalogPersistenceError",
    "DataFrameSchemaMapper",
    "DataFrameSchemaMapping",
    "DataFrameSchemaMappingError",
    "DbCatalogDatasetSchemaSource",
    "NodeDslExpressionResolver",
    "SQLAlchemyCatalogProjectSource",
    "SQLAlchemyDatasetConnectionRepository",
    "SQLAlchemyDatasetFieldRepository",
    "SQLAlchemyDatasetLinkRepository",
    "SQLAlchemyDatasetRepository",
    "SQLAlchemyProjectGraphGateway",
    "SQLAlchemyProjectionRepository",
    "SQLConnectionLocatorGateway",
    "SqlglotTableReferenceExtractor",
    "build_observation",
    "to_graph_input_value",
]


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
