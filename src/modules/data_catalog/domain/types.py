from enum import Enum, StrEnum, auto

LINEAGE_SCHEMA_VERSION = 1
"""Версия семантики каталожной проекции; бамп инвалидирует все проекции без миграции."""


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
