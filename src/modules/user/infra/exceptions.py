from src.exception_registry import RegisteredException


class UserInfraException(RegisteredException):
    category = "User"
    type = "Infrastructure"
