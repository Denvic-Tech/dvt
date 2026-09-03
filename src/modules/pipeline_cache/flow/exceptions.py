class PipelineCacheFlowError(Exception):
    """Base exception for pipeline cache flow failures."""


class JSONDataNotFoundError(PipelineCacheFlowError):
    """Raised when cached JSON data cannot be restored."""


class DataFrameMetadataNotFoundError(PipelineCacheFlowError):
    """Raised when dataframe metadata is missing in cache."""


class DataFramePartitionNotFoundError(PipelineCacheFlowError):
    """Raised when dataframe partition index is missing in cache."""
