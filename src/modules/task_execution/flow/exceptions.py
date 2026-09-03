from src.exception_registry import RegisteredException


class TaskExecutionFlowError(RegisteredException):
    """Use named flow exceptions instead of raising RegisteredException directly."""

    name = "TASK_EXECUTION_FLOW_ERROR"
    code = "TASK_EXECUTION_FLOW_001"
    category = "TASK_EXECUTION_FLOW_ERROR"
    description = "Task execution application flow error"


class InvalidReconciliationTerminationReason(TaskExecutionFlowError):
    name = "TASK_EXECUTION_INVALID_RECONCILIATION_REASON"
    code = "TASK_EXECUTION_FLOW_002"
    description = "Termination reason is not valid for execution reconciliation"


class InvalidPendingExecutionFailureReason(TaskExecutionFlowError):
    name = "TASK_EXECUTION_INVALID_PENDING_FAILURE_REASON"
    code = "TASK_EXECUTION_FLOW_003"
    description = "Termination reason is not valid for pending execution failure"
