from src.exception_registry.exception_types import ExceptionCategory
from src.exception_registry.registered_exception import RegisteredException


class QueueTopicNotFoundException(RegisteredException):
    name = "CRUD_QUEUE_TOPIC_NOT_FOUND"
    code = "CRUD_QUEUE_TOPIC_404"
    description = "Топик очереди не найден"
    category = ExceptionCategory.CRUD_QUEUE_TOPIC.value


class QueueTopicAlreadyExistsException(RegisteredException):
    name = "CRUD_QUEUE_TOPIC_ALREADY_EXISTS"
    code = "CRUD_QUEUE_TOPIC_409"
    description = "Топик очереди уже существует"
    category = ExceptionCategory.CRUD_QUEUE_TOPIC.value
