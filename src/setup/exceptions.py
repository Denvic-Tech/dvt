class SetupConflictError(RuntimeError):
    """Raised when a setup step is already completed or cannot be repeated."""


class SetupValidationError(ValueError):
    """Raised when setup payload is structurally invalid."""

    def __init__(self, message: str, *, fields: dict[str, str] | None = None):
        super().__init__(message)
        self.fields = fields or {}
