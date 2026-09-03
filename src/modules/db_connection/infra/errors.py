from db_connection import (
    ConnectionLimitExceededError,
    ConnectionNotFoundError,
    ConnectionTypeNotSupportedError,
    DBConnectionError,
    ErrorResponseSpec,
    InfrastructureError,
    SecretDecryptionError,
    ValidationFailedError,
)
from db_connection.errors import AccessDeniedError, ErrorMapper

from src.logger import logger

from .exceptions import DBConnectionInfraException


class DVTErrorMapper(ErrorMapper):
    def map_exception(self, exc: Exception) -> ErrorResponseSpec:
        if isinstance(exc, AccessDeniedError):
            return ErrorResponseSpec(403, exc.code, exc.message, exc.details)
        if isinstance(exc, ConnectionNotFoundError):
            return ErrorResponseSpec(404, exc.code, exc.message, exc.details)
        if isinstance(exc, ConnectionTypeNotSupportedError):
            return ErrorResponseSpec(400, exc.code, exc.message, exc.details)
        if isinstance(exc, ValidationFailedError):
            return ErrorResponseSpec(422, exc.code, exc.message, exc.details)
        if isinstance(exc, ConnectionLimitExceededError):
            return ErrorResponseSpec(409, exc.code, exc.message, exc.details)
        if isinstance(exc, (InfrastructureError, SecretDecryptionError, DBConnectionInfraException)):
            return ErrorResponseSpec(500, exc.code, exc.message, exc.details)
        if isinstance(exc, DBConnectionError):
            return ErrorResponseSpec(400, exc.code, exc.message, exc.details)

        logger.exception("Unhandled exception")
        return ErrorResponseSpec(
            500,
            "internal_error",
            "Internal server error.",
        )
