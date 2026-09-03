class SQLCodeMetadataDomainError(Exception):
    """Базовое исключение bounded context анализа SQL-кода."""


class SQLValidationError(SQLCodeMetadataDomainError):
    """Сигнализирует о детерминированной ошибке SQL-валидации."""


class SQLCodeMetadataError(SQLCodeMetadataDomainError):
    """Сигнализирует об ошибке извлечения SQL metadata."""
