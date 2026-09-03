class SetupConflictError(RuntimeError):
    """Raised when a setup step is already completed or cannot be repeated."""


class SetupValidationError(ValueError):
    """Raised when setup payload is structurally invalid."""
