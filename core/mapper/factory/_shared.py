import sys

from sqlalchemy import DateTime

try:
    from sqlalchemy.dialects.postgresql import TIMESTAMP as PGTimestamp
    from clickhouse_sqlalchemy.types import DateTime as CHDatetime, Nullable
    from clickhouse_sqlalchemy.drivers.base import ClickHouseDialect
    from clickhouse_sqlalchemy.engines import MergeTree
    from sqlalchemy.dialects.mysql import VARCHAR

    CH_TYPES = sys.modules['clickhouse_sqlalchemy.types']
except ImportError:
    ClickHouseDialect = type('ClickHouseDialect', (), {})
    MergeTree = None
    CHDatetime = DateTime
    CH_TYPES = None
    Nullable = None
    VARCHAR = None

INT32_MIN, INT32_MAX = -2 ** 31, 2 ** 31 - 1
DECIMAL_MAX_PRECISION = 38
DECIMAL_MAX_SCALE = 10