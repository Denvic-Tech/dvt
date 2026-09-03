class WriteV3Error(Exception):
    """Base class for all write_v3 errors."""


class WriteV3ConfigError(WriteV3Error):
    """Invalid user configuration for write_v3."""


class WriteV3PlanningError(WriteV3Error):
    """Planner could not construct a strict write plan."""


class WriteV3ExecutionError(WriteV3Error):
    """Executor failed while writing data."""


class WriteV3DialectError(WriteV3Error):
    """Dialect-specific write operation is unsupported or invalid."""
