from src.exception_registry.exception_types import ExceptionCategory
from src.exception_registry.registered_exception import RegisteredException


class SubgraphNotFoundException(RegisteredException):
    name = "CRUD_SUBGRAPH_NOT_FOUND"
    code = "CRUD_SUBGRAPH_404"
    description = "Подграф не найден"
    category = ExceptionCategory.CRUD_SUBGRAPH.value
