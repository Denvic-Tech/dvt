from src.exception_registry.exception_types import ExceptionCategory
from src.exception_registry.registered_exception import RegisteredException


class GraphNotFoundException(RegisteredException):
    name = "CRUD_GRAPH_NOT_FOUND"
    code = "CRUD_GRAPH_404"
    description = "Граф не найден"
    category = ExceptionCategory.CRUD_GRAPH.value
