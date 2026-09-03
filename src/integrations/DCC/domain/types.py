from enum import StrEnum


class TaskStatus(StrEnum):
    RECEIVED = "received"
    STARTED = "started"
    ERROR = "error"
    SUCCESS = "success"
    WAITING = "waiting"
