from enum import StrEnum


class PipelineExecutionMode(StrEnum):
    """Execution mode of a pipeline, independent from task transport/lifecycle."""

    FULL = "full"
    METADATA_ONLY = "metadata_only"
