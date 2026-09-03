class WriteV4Error(Exception):
    """Base class for all write_v4 errors."""


class WriteV4ConfigError(WriteV4Error):
    """Invalid user configuration for write_v4."""


class WriteV4PlanningError(WriteV4Error):
    """Planner could not construct a strict write plan."""


class WriteV4ExecutionError(WriteV4Error):
    """Executor failed while writing data."""


class WriteV4DialectError(WriteV4Error):
    """Dialect-specific write operation is unsupported or invalid."""
