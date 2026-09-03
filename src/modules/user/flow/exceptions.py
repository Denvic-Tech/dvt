from src.exception_registry import RegisteredException


class UserFlowException(RegisteredException):
    category = "User"
    type = "Flow"


class UserNotFoundError(UserFlowException):
    name = "User not found"
    code = "USER_NOT_FOUND"

    def __init__(self, user_id: str | None) -> None:

        description = "User "

        if user_id:
            description += f"ID='{user_id}' "

        description += "not found"

        super().__init__(description=description)
