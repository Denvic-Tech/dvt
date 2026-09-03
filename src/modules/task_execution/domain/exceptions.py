from src.exception_registry import RegisteredException


class TaskExecutionDomainError(RegisteredException):
    """Use named domain exceptions instead of raising RegisteredException directly."""

    name = "TASK_EXECUTION_DOMAIN_ERROR"
    code = "TASK_EXECUTION_DOMAIN_001"
    category = "TASK_EXECUTION_DOMAIN_ERROR"
    description = "Task execution domain error"
