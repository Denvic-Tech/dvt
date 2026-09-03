from src.exception_registry.exception_types import ExceptionCategory
from src.exception_registry.registered_exception import RegisteredException


class GraphNodeNotFoundException(RegisteredException):
    name = "CRUD_GRAPH_NODE_NOT_FOUND"
    code = "CRUD_GRAPH_NODE_404"
    description = "Узел графа не найден"
    category = ExceptionCategory.CRUD_GRAPH_NODE.value
