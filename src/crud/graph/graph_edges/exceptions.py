from src.exception_registry.exception_types import ExceptionCategory
from src.exception_registry.registered_exception import RegisteredException


class GraphEdgeNotFoundException(RegisteredException):
    name = "CRUD_GRAPH_EDGE_NOT_FOUND"
    code = "CRUD_GRAPH_EDGE_404"
    description = "Ребро графа не найдено"
    category = ExceptionCategory.CRUD_GRAPH_EDGE.value
