from src.exception_registry import RegisteredException


class DataCatalogFlowError(RegisteredException):
    category = "DATA_CATALOG_FLOW_ERROR"


class ProjectionRebuildFailedError(DataCatalogFlowError):
    name = "DATA_CATALOG_PROJECTION_REBUILD_FAILED"
    code = "DATA_CATALOG_011"
    description = "Data catalog projection rebuild failed."
