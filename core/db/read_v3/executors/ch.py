from core.db.read_v3.executors.sql import SQLReadExecutor


class ClickHouseReadExecutor(SQLReadExecutor):
    """Dedicated class name for explicit ClickHouse resolver wiring."""
