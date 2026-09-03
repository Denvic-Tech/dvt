from src.exception_registry import RegisteredException


class DBConnectionInfraException(RegisteredException):
    category = "DBConnectionV1"
    type = "Infrastructure"
