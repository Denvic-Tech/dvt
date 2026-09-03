class NodeDSLException(Exception):
    """Базовое исключение для всех ошибок в Node DSL."""
    pass


class NodeRegistrationError(NodeDSLException):
    def __init__(self, message: str = "Node registration failed"):
        """Исключение для ошибок регистрации ноды."""
        super().__init__(message)


class NodeValidationError(NodeDSLException):
    def __init__(self, message: str = "Node validation failed"):
        """Исключение для ошибок валидации ноды."""
        super().__init__(message)
