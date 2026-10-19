from enum import StrEnum

BUNDLE_FORMAT_VERSION = 1
BUNDLE_FILE_EXTENSION = ".dvtpkg"


class ImportMode(StrEnum):
    CREATE = "create"
    MERGE = "merge"


class MergeStrategy(StrEnum):
    REPLACE = "replace"
    APPEND = "append"


class ConnectionDecisionAction(StrEnum):
    USE_EXISTING = "use_existing"
    CREATE = "create"
    SKIP = "skip"


class ConflictDecision(StrEnum):
    KEEP = "keep"
    OVERWRITE = "overwrite"


class TransferWarningCode(StrEnum):
    UNKNOWN_NODE = "unknown_node"
    EXTENSION_UNAVAILABLE = "extension_unavailable"
    CONNECTION_INACCESSIBLE = "connection_inaccessible"
    CONNECTION_SKIPPED = "connection_skipped"
    CONNECTION_NOT_FOUND = "connection_not_found"
    CONNECTION_CREATE_FAILED = "connection_create_failed"
    SECRETS_UNAVAILABLE = "secrets_unavailable"
    SCHEDULE_FORBIDDEN = "schedule_forbidden"
    SCHEDULE_DISABLE_FAILED = "schedule_disable_failed"
    SCHEDULE_IMPORT_FAILED = "schedule_import_failed"
    SCHEDULE_EXISTS = "schedule_exists"
    VARIABLE_CONFLICT = "variable_conflict"
    CATALOG_REBUILD_FAILED = "catalog_rebuild_failed"
