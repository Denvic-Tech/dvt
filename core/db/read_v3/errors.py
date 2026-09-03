class ReadV3Error(Exception):
    """Base class for all read_v3 errors."""


class ReadV3ConfigError(ReadV3Error):
    """Invalid user configuration for read_v3."""


class ReadV3PlanningError(ReadV3Error):
    """Planner could not construct a strict execution plan."""


class ReadV3ExecutionError(ReadV3Error):
    """Executor failed to run a plan segment in strict mode."""


class ReadV3DialectError(ReadV3Error):
    """Dialect-specific operation is unsupported or invalid."""
