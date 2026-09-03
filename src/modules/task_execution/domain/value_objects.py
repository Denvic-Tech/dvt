from dataclasses import dataclass


@dataclass(frozen=True)
class TaskExecutionId:
    value: str
