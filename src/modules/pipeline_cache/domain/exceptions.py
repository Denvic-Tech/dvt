class PipelineCacheDomainError(Exception):
    """Base exception for pipeline cache domain errors."""


class InvalidIndexKeyError(PipelineCacheDomainError):
    """Raised when an index key cannot be serialized or parsed."""
