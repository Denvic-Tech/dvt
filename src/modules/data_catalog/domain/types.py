from enum import Enum, StrEnum, auto

LINEAGE_SCHEMA_VERSION = 2
"""Версия семантики каталожной проекции; бамп инвалидирует все проекции без миграции."""

MAX_COLUMNS_PER_PORT = 2000
"""Защита документа lineage от взрывного роста: лишние колонки порта отбрасываются с диагностикой."""


class Unset(Enum):
    """Маркер «значение не передано», отличающий пропуск от явного None."""

    UNSET = auto()


UNSET = Unset.UNSET


class DescriptionProvenance(StrEnum):
    DECLARED = "declared"
    SOURCE = "source"
    NONE = "none"


class FieldStatus(StrEnum):
    OK = "ok"
    NEW = "new"
    MISSING = "missing"
    TYPE_CHANGED = "type_changed"


class LinkDirection(StrEnum):
    READ = "read"
    WRITE = "write"


class LinkKind(StrEnum):
    DECLARED = "declared"


class ResolvedVia(StrEnum):
    CONST = "const"
    EXPRESSION = "expression"
    SQL = "sql"


class ProjectionStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"


class ViewerScope(StrEnum):
    ALL = "all"
    ORGANIZATION = "organization"
    OWN = "own"


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNVERIFIED = "unverified"
    UNREACHABLE = "unreachable"
    NOT_FOUND = "not_found"


class CheckErrorKind(StrEnum):
    """Почему последняя проверка схемы не удалась: объекта нет или источник недоступен."""

    NOT_FOUND = "not_found"
    UNREACHABLE = "unreachable"


class LocatorKind(StrEnum):
    EXPLICIT = "explicit"
    SQL = "sql"
    VARIABLES = "variables"


class LineageOp(StrEnum):
    SOURCE = "source"
    PASS = "pass"
    RENAME = "rename"
    COMPUTE = "compute"
    AGGREGATE = "aggregate"
    MERGE = "merge"
    UNKNOWN = "unknown"


class RefKind(StrEnum):
    DATASET_FIELD = "ds"
    NODE_COLUMN = "node"


class PortStatus(StrEnum):
    RESOLVED = "resolved"
    PARTIALLY_RESOLVED = "partially_resolved"
    UNRESOLVED = "unresolved"


class LineageProvenance(StrEnum):
    """Откуда текст описания колонки.

    `none`: источник известен, но текста у него нет (поле без описания и комментария и всё,
    что от него унаследовано); `unknown`: происхождение колонки не восстановлено.
    """

    DECLARED = "declared"
    SOURCE = "source"
    INHERITED = "inherited"
    DERIVED = "derived"
    NONE = "none"
    UNKNOWN = "unknown"


class ExplainDirection(StrEnum):
    UPSTREAM = "upstream"
    DOWNSTREAM = "downstream"


class SqlColumnKind(StrEnum):
    COLUMN = "column"
    EXPRESSION = "expression"
    AGGREGATE = "aggregate"
    UNION = "union"
    LITERAL = "literal"
    UNKNOWN = "unknown"


class DiagnosticReason(StrEnum):
    CONNECTION_NOT_STATIC = "connection_not_static"
    CONNECTION_MISSING = "connection_missing"
    CONNECTION_EDGE_MISSING = "connection_edge_missing"
    EXPRESSION_UNRESOLVED = "expression_unresolved"
    SQL_PARSE_FAILED = "sql_parse_failed"
    SQL_TEMPLATE_UNRESOLVED = "sql_template_unresolved"
    LOCATOR_INPUT_MISSING = "locator_input_missing"
    LINK_INPUT_UNSUPPORTED = "link_input_unsupported"
    UNSUPPORTED_DIALECT = "unsupported_dialect"
    LINEAGE_RULE_MISSING = "lineage_rule_missing"
    LINEAGE_NODE_DEFINITION_MISSING = "lineage_node_definition_missing"
    LINEAGE_INPUT_DYNAMIC = "lineage_input_dynamic"
    LINEAGE_INPUT_INVALID = "lineage_input_invalid"
    LINEAGE_INPUT_MISSING = "lineage_input_missing"
    LINEAGE_SCHEMA_NOT_SYNCED = "lineage_schema_not_synced"
    LINEAGE_SOURCE_NOT_STATIC = "lineage_source_not_static"
    LINEAGE_SQL_UNSUPPORTED = "lineage_sql_unsupported"
    LINEAGE_DUPLICATE_COLUMN = "lineage_duplicate_column"
    LINEAGE_TRUNCATED = "lineage_truncated"
    LINEAGE_CYCLE = "lineage_cycle"
    LINEAGE_FAILED = "lineage_failed"
