import os
from pathlib import Path
from typing import Literal

_TRUE_STATEMENT_TOKENS = ("true", "yes", "1", "on")


def _get_positive_int_env(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


class COMMON:
    SERVICE_NAME = os.getenv("SERVICE_NAME", "no-service-name")
    ENVIRONMENT: Literal["dev", "prod"] = os.getenv("ENVIRONMENT", "dev")


def _get_security_secret(name: str, dev_default: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    return dev_default if COMMON.ENVIRONMENT == "dev" else ""


class PROJECT:
    ROOT_DIR = Path(__file__).parent
    INSTALLATION_DIR = ROOT_DIR / "installation"
    INSTALLATION_IDENTITY_FILE = INSTALLATION_DIR / "instance_id"
    DATA_DIR = ROOT_DIR / "data"
    NODE_DOCUMENTATION_DIR = ROOT_DIR / "docs" / "nodes"
    SRC_DIR = ROOT_DIR / "src"
    TESTS_DIR = ROOT_DIR / "tests"
    LOCALES_DIR = ROOT_DIR / "locales"
    NODES_DIR = SRC_DIR / "nodes"
    EXTENSIONS_DIR = ROOT_DIR / "extensions"

    ALEMBIC_INI = ROOT_DIR / "alembic.ini"
    RELEASE_FILE = ROOT_DIR / "RELEASE"
    PYPROJECT_TOML = ROOT_DIR / "pyproject.toml"


def get_version_from_pyproject() -> str:
    import tomli

    try:
        with open(PROJECT.PYPROJECT_TOML, "rb") as f:
            data = tomli.load(f)
        version = data.get("project", {}).get("version")
        if version:
            return version
    except Exception:
        pass
    return "0.0.0"


class APP:
    VERSION: str = get_version_from_pyproject()
    # Канал для фильтрации версий для prod
    CHANNEL: str = COMMON.ENVIRONMENT


class DEBUG:
    DEBUG = os.getenv("DEBUG", "false").lower() in _TRUE_STATEMENT_TOKENS
    SQL_ECHO = os.getenv("DEBUG_SQL_ECHO", "false").lower() in _TRUE_STATEMENT_TOKENS


class LOGGING:
    LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
    LOG_TO_FILE = os.getenv("LOG_TO_FILE", "false").lower() in _TRUE_STATEMENT_TOKENS
    LOG_LEVEL_TO_FILE = os.getenv("LOG_LEVEL_TO_FILE", LOG_LEVEL).upper()
    LOG_TO_DB = os.getenv("LOG_TO_DB", "false").lower() in _TRUE_STATEMENT_TOKENS
    LOG_TO_WS = os.getenv("LOG_TO_WS", "true").lower() in _TRUE_STATEMENT_TOKENS
    INTERCEPT_STANDARD_LOGGING = os.getenv("INTERCEPT_STANDARD_LOGGING", "false").lower() in _TRUE_STATEMENT_TOKENS
    LOG_TRACEBACK_MAX_LINES = int(os.getenv("LOG_TRACEBACK_MAX_LINES", "20"))
    MAX_MEMORY_LOGS = 10_000

    LOGGING_CONFIG_FILE = PROJECT.ROOT_DIR / "logging.yaml"
    LOGS_CLEANUP_TRESHOLD_DAYS = int(os.getenv("LOGS_CLEANUP_THRESHOLD_DAYS", "30"))
    LOGS_CLEANUP_BATCH_SIZE = int(os.getenv("LOGS_CLEANUP_BATCH_SIZE", "1000"))
    LOGS_CLEANUP_ADVISORY_LOCK_KEY = int(os.getenv("LOGS_CLEANUP_ADVISORY_LOCK_KEY", "1234567890"))
    LOGS_CLEANUP_CRON = os.getenv("LOGS_CLEANUP_CRON", "0 3 * * *")
    LOG_BATCH_SIZE = int(os.getenv("LOG_BATCH_SIZE", "200"))
    LOG_FLUSH_INTERVAL_SEC = int(os.getenv("LOG_FLUSH_INTERVAL_SEC", "1"))
    LOG_QUEUE_MAXSIZE = int(os.getenv("LOG_QUEUE_MAXSIZE", "10000"))


class NODES:
    DISABLED_NODES = os.getenv("DISABLED_NODES", "").split(";")  # Формат <Имя ноды>;<Имя ноды 2>
    DISABLED_TAGS = os.getenv("DISABLED_TAGS", "").split(";")
    DISABLED_CATEGORIES = os.getenv("DISABLED_CATEGORIES", "").split(";")

    if COMMON.ENVIRONMENT == "prod":
        DISABLED_CATEGORIES += ["Testing"]
        DISABLED_TAGS += ["Deprecated", "Unstable", "Not tested"]


class EXTENSIONS:
    __default_distributor_url = "https://extensions.distribution.denvic.tech"

    DISTRIBUTOR_URL = os.getenv("EXTENSIONS_DISTRIBUTOR_URL", __default_distributor_url)
    ENABLED = os.getenv("EXTENSIONS_ENABLED", "true").lower() in _TRUE_STATEMENT_TOKENS
    MANIFEST_FILE = os.getenv("EXTENSIONS_MANIFEST_FILE", "pyproject.toml")
    AUTOLOAD = os.getenv("EXTENSIONS_AUTOLOAD", "true").lower() in _TRUE_STATEMENT_TOKENS
    PENDING_DELETIONS_FILE = PROJECT.DATA_DIR / "extensions_pending_deletions.json"
    EXTENSIONS_DATA_DIR = os.getenv("EXTENSIONS_DATA_DIR", PROJECT.EXTENSIONS_DIR)

    if not DISTRIBUTOR_URL:
        DISTRIBUTOR_URL = __default_distributor_url


class SECURITY:
    JWT_ACCESS_TOKEN_SECRET_KEY = _get_security_secret(
        "JWT_ACCESS_TOKEN_SECRET_KEY",
        "dev-only-jwt-access-secret-change-me",
    )
    JWT_REFRESH_TOKEN_SECRET_KEY = _get_security_secret(
        "JWT_REFRESH_TOKEN_SECRET_KEY",
        "dev-only-jwt-refresh-secret-change-me",
    )
    JWT_ONETIME_TOKEN_SECRET_KEY = _get_security_secret(
        "JWT_ONETIME_TOKEN_SECRET_KEY",
        "dev-only-jwt-onetime-secret-change-me",
    )
    JWT_API_TOKEN_SECRET_KEY = _get_security_secret(
        "JWT_API_TOKEN_SECRET_KEY",
        "dev-only-jwt-api-secret-change-me",
    )
    CODE_HASH_SALT = _get_security_secret(
        "CODE_HASH_SALT",
        "dev-only-code-hash-salt-change-me",
    )
    FERNET_KEY = os.getenv("FERNET_KEY", "Y8RFpaIxSaAFNsB352tpLXl5znUw5anEKIZgclOezak=")

    _AUTH_SECRET_NAMES = (
        "JWT_ACCESS_TOKEN_SECRET_KEY",
        "JWT_REFRESH_TOKEN_SECRET_KEY",
        "JWT_ONETIME_TOKEN_SECRET_KEY",
        "JWT_API_TOKEN_SECRET_KEY",
        "CODE_HASH_SALT",
    )
    _AUTH_SECRET_MIN_LENGTH = 32

    @classmethod
    def validate(cls) -> None:
        if COMMON.ENVIRONMENT != "prod":
            return

        values = {name: getattr(cls, name) for name in cls._AUTH_SECRET_NAMES}
        missing = [name for name, value in values.items() if not value]
        too_short = [
            name
            for name, value in values.items()
            if value and len(value) < cls._AUTH_SECRET_MIN_LENGTH
        ]
        duplicate_names = sorted(
            name
            for name, value in values.items()
            if value and list(values.values()).count(value) > 1
        )

        errors: list[str] = []
        if missing:
            errors.append(f"missing: {', '.join(missing)}")
        if too_short:
            errors.append(
                f"shorter than {cls._AUTH_SECRET_MIN_LENGTH} characters: "
                f"{', '.join(too_short)}"
            )
        if duplicate_names:
            errors.append(f"must be unique: {', '.join(duplicate_names)}")
        if errors:
            raise RuntimeError("Invalid production auth secrets; " + "; ".join(errors))


class CLICKHOUSE:
    HTTP_POOL_MAXSIZE = _get_positive_int_env("CLICKHOUSE_HTTP_POOL_MAXSIZE", 8)


class POSTGRES:
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
    POSTGRES_PORT = os.getenv("POSTGRES_PORT", "15433")
    POSTGRES_DB = os.getenv("POSTGRES_DB", "DVT")
    POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
    MIGRATION_WAIT_TIMEOUT_SEC = _get_positive_int_env("MIGRATION_WAIT_TIMEOUT_SEC", 300)

    DATABASE_URL = f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"


class VALKEY:
    VALKEY_HOST = os.getenv("VALKEY_HOST", "127.0.0.1")
    VALKEY_PORT = os.getenv("VALKEY_PORT", "16379")
    VALKEY_PASSWORD = os.getenv("VALKEY_PASSWORD", "valkeypass")
    VALKEY_DB = int(os.getenv("VALKEY_DB", "0"))

    VALKEY_URL = "redis://" + (f":{VALKEY_PASSWORD}@" if VALKEY_PASSWORD else "") + f"{VALKEY_HOST}:{VALKEY_PORT}/{VALKEY_DB}"


class CELERY:
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", VALKEY.VALKEY_URL)
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
    CELERY_TASKS_QUEUE = os.getenv("CELERY_TASKS_QUEUE", "tasks.worker")
    CELERY_DEPS_EXCHANGE = os.getenv("CELERY_DEPS_EXCHANGE", "tasks.deps")
    CELERY_DEPS_QUEUE = os.getenv("CELERY_DEPS_QUEUE", "tasks.deps")
    CELERY_HEARTBEAT_CHANNEL = os.getenv("CELERY_HEARTBEAT_CHANNEL", "workers.heartbeat")
    CELERY_WORKER_PREFETCH_MULTIPLIER = int(os.getenv("CELERY_WORKER_PREFETCH_MULTIPLIER", "1"))
    CELERY_TASK_ACKS_LATE = os.getenv("CELERY_TASK_ACKS_LATE", "true").lower() in _TRUE_STATEMENT_TOKENS
    CELERY_VISIBILITY_TIMEOUT_SEC = _get_positive_int_env("CELERY_VISIBILITY_TIMEOUT_SEC", 28_800)

class ORCHESTRATOR:
    ORCH_EVENTS_STREAM = os.getenv("ORCH_EVENTS_STREAM", "orchestrator.events")
    ORCH_EVENTS_MAXLEN = int(os.getenv("ORCH_EVENTS_MAXLEN", "100"))
    ORCH_EVENTS_GROUP = os.getenv("ORCH_EVENTS_GROUP", "orchestrator-events")
    ORCH_EVENTS_CONSUMER = os.getenv("ORCH_EVENTS_CONSUMER", COMMON.SERVICE_NAME)
    ORCH_EVENTS_BLOCK_MS = int(os.getenv("ORCH_EVENTS_BLOCK_MS", "2000"))
    ORCH_EVENTS_BATCH_SIZE = int(os.getenv("ORCH_EVENTS_BATCH_SIZE", "50"))
    ORCH_STREAM_PENDING_IDLE_SEC = float(os.getenv("ORCH_STREAM_PENDING_IDLE_SEC", "15"))
    ORCH_COMMANDS_STREAM = os.getenv("ORCH_COMMANDS_STREAM", "orchestrator.commands")
    ORCH_COMMANDS_MAXLEN = int(os.getenv("ORCH_COMMANDS_MAXLEN", "100"))
    ORCH_COMMANDS_GROUP = os.getenv("ORCH_COMMANDS_GROUP", "orchestrator-commands")
    ORCH_COMMANDS_CONSUMER = os.getenv("ORCH_COMMANDS_CONSUMER", COMMON.SERVICE_NAME)
    ORCH_COMMANDS_BLOCK_MS = int(os.getenv("ORCH_COMMANDS_BLOCK_MS", "2000"))
    ORCH_COMMANDS_BATCH_SIZE = int(os.getenv("ORCH_COMMANDS_BATCH_SIZE", "50"))

    ORCHESTRATOR_HOST = os.getenv("ORCHESTRATOR_HOST", "127.0.0.1")
    ORCHESTRATOR_PORT = int(os.getenv("ORCHESTRATOR_PORT", 8250))
    ORCHESTRATOR_URL = f"{ORCHESTRATOR_HOST}:{ORCHESTRATOR_PORT}"
    ORCHESTRATOR_TOKEN = os.getenv("ORCHESTRATOR_TOKEN", "secret-orchestrator-token-123")
    ORCHESTRATOR_SCHEDULER_INTERVAL_SEC = 1
    ORCHESTRATOR_HEARTBEAT_TIMEOUT_SEC = 10
    ORCHESTRATOR_APP_CONFIG_CACHE_TTL_SEC = float(
        os.getenv("ORCHESTRATOR_APP_CONFIG_CACHE_TTL_SEC", "5")
    )
    ORCHESTRATOR_EXECUTION_SUPERVISOR_INTERVAL_SEC = float(
        os.getenv("ORCHESTRATOR_EXECUTION_SUPERVISOR_INTERVAL_SEC", "2")
    )
    ORCHESTRATOR_EXECUTION_TELEMETRY_STALE_TIMEOUT_SEC = float(
        os.getenv("ORCHESTRATOR_EXECUTION_TELEMETRY_STALE_TIMEOUT_SEC", "8")
    )
    ORCHESTRATOR_OOM_GUARD_COOLDOWN_SEC = float(
        os.getenv("ORCHESTRATOR_OOM_GUARD_COOLDOWN_SEC", "15")
    )
    TASK_STOP_GRACE_PERIOD_SEC = float(os.getenv("TASK_STOP_GRACE_PERIOD_SEC", "10"))


class GATEWAY:
    GATEWAY_HOST = os.getenv("GATEWAY_HOST", "127.0.0.1")
    GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", 8200))
    GATEWAY_URL = f"http://{GATEWAY_HOST}"

    if GATEWAY_PORT != 80:
        GATEWAY_URL += f":{GATEWAY_PORT}"

    GATEWAY_COOKIE_SECURE = os.getenv("GATEWAY_COOKIE_SECURE", "yes").lower() in _TRUE_STATEMENT_TOKENS
    GATEWAY_ORIGINS = [url.rstrip("/") for url in
                       os.getenv("GATEWAY_ORIGINS", f"http://localhost:5173;http://localhost:8000").split(";")]


class DB_CATALOG:
    CACHE_TTL_SEC = int(os.getenv("DB_CATALOG_CACHE_TTL_SEC", "60"))
    CONNECT_TIMEOUT_SEC = int(os.getenv("DB_CATALOG_CONNECT_TIMEOUT_SEC", "5"))
    QUERY_TIMEOUT_SEC = int(os.getenv("DB_CATALOG_QUERY_TIMEOUT_SEC", "30"))
    REQUEST_TIMEOUT_SEC = int(os.getenv("DB_CATALOG_REQUEST_TIMEOUT_SEC", "40"))
    SINGLEFLIGHT_LOCK_TTL_SEC = int(os.getenv("DB_CATALOG_SINGLEFLIGHT_LOCK_TTL_SEC", "35"))
    MAX_CONCURRENCY = int(os.getenv("DB_CATALOG_MAX_CONCURRENCY", "16"))
    PREVIEW_CELL_MAX_CHARS = _get_positive_int_env(
        "DB_CATALOG_PREVIEW_CELL_MAX_CHARS",
        4096,
    )
    PREVIEW_MAX_RESPONSE_BYTES = _get_positive_int_env(
        "DB_CATALOG_PREVIEW_MAX_RESPONSE_BYTES",
        1024 * 1024,
    )


class AI_ANALYSIS:
    ENABLED = os.getenv("DVT_ENABLE_AI_ANALYSIS", "false").lower() in _TRUE_STATEMENT_TOKENS
    SERVICE_URL = os.getenv("DVT_AI_SERVICE_URL", "").rstrip("/")
    SERVICE_API_KEY = os.getenv("DVT_AI_SERVICE_API_KEY", "")
    REQUEST_TIMEOUT_SEC = float(os.getenv("DVT_AI_ANALYSIS_REQUEST_TIMEOUT_SEC", "120"))
    STATUS_POLL_INTERVAL_SEC = float(os.getenv("DVT_AI_ANALYSIS_STATUS_POLL_INTERVAL_SEC", "2"))


class AI_MCP:
    ENABLED = os.getenv("DVT_AI_MCP_ENABLED", "false").lower() in _TRUE_STATEMENT_TOKENS
    INTERNAL_SECRET = os.getenv(
        "DVT_AI_MCP_INTERNAL_SECRET",
        "dev-ai-mcp-internal-secret-change-me" if COMMON.ENVIRONMENT == "dev" else "",
    )
    INTERNAL_SECRET_MIN_LENGTH = 32
    SQL_QUERY_TIMEOUT_SEC = _get_positive_int_env("DVT_AI_MCP_SQL_QUERY_TIMEOUT_SEC", 30)
    SQL_MAX_ROWS = _get_positive_int_env("DVT_AI_MCP_SQL_MAX_ROWS", 1000)
    SQL_MAX_RESPONSE_BYTES = _get_positive_int_env(
        "DVT_AI_MCP_SQL_MAX_RESPONSE_BYTES",
        1024 * 1024,
    )
    STORAGE_PREVIEW_MAX_BYTES = _get_positive_int_env(
        "DVT_AI_MCP_STORAGE_PREVIEW_MAX_BYTES",
        256 * 1024,
    )
    STORAGE_PREVIEW_MAX_DOWNLOAD_BYTES = _get_positive_int_env(
        "DVT_AI_MCP_STORAGE_PREVIEW_MAX_DOWNLOAD_BYTES",
        10 * 1024 * 1024,
    )

    @classmethod
    def validate(cls) -> None:
        if not cls.ENABLED:
            return
        if len(cls.INTERNAL_SECRET) < cls.INTERNAL_SECRET_MIN_LENGTH:
            raise RuntimeError(
                "DVT_AI_MCP_INTERNAL_SECRET must contain at least "
                f"{cls.INTERNAL_SECRET_MIN_LENGTH} characters."
            )


class TASK_WORKER:
    TASK_WORKER_MAX_CONCURRENT = os.getenv("TASK_WORKER_MAX_CONCURRENT", "1")
    TASK_WORKER_HEARTBEAT_INTERVAL = int(os.getenv("TASK_WORKER_HEARTBEAT_INTERVAL", "2"))
    CELERY_WORKER_CONCURRENCY = int(os.getenv("CELERY_WORKER_CONCURRENCY", TASK_WORKER_MAX_CONCURRENT))
    TASK_EXECUTION_TELEMETRY_INTERVAL_SEC = float(
        os.getenv("TASK_EXECUTION_TELEMETRY_INTERVAL_SEC", "2")
    )
    TASK_CANCELLATION_POLL_INTERVAL_SEC = float(
        os.getenv("TASK_CANCELLATION_POLL_INTERVAL_SEC", "0.5")
    )
    # Recycling is only a safety net; task-scoped cleanup is the normal lifecycle.
    CELERY_WORKER_MAX_TASKS_PER_CHILD = (
        int(os.environ["CELERY_WORKER_MAX_TASKS_PER_CHILD"])
        if os.getenv("CELERY_WORKER_MAX_TASKS_PER_CHILD") else None
    )
    CELERY_WORKER_MAX_MEMORY_PER_CHILD = (
        int(os.environ["CELERY_WORKER_MAX_MEMORY_PER_CHILD"])
        if os.getenv("CELERY_WORKER_MAX_MEMORY_PER_CHILD") else None
    )


class PROJECT_SCHEDULER:
    PROJECT_SCHEDULER_HOST = os.getenv("PROJECT_SCHEDULER_HOST", "127.0.0.1")
    PROJECT_SCHEDULER_PORT = int(os.getenv("PROJECT_SCHEDULER_PORT", 8201))
    PROJECT_SCHEDULER_URL = f"http://{PROJECT_SCHEDULER_HOST}"
    if PROJECT_SCHEDULER_PORT != 80:
        PROJECT_SCHEDULER_URL += f":{PROJECT_SCHEDULER_PORT}"


class OTHER:
    BULK_INSERT_NUM_WORKERS = int(os.getenv(f"BULK_INSERT_NUM_WORKERS", 8))
    SQL_BULK_INSERT_MAX_WORKERS = int(os.getenv("SQL_BULK_INSERT_MAX_WORKERS", 32))
    SQL_ENGINE_MAX_CONNECTIONS = int(os.getenv("SQL_ENGINE_MAX_CONNECTIONS", 32))
    SQL_ENGINE_POOL_TIMEOUT_SEC = int(os.getenv("SQL_ENGINE_POOL_TIMEOUT_SEC", 30))
    REDIS_IDLE_CONNECTION_TTL_SEC = int(os.getenv("REDIS_IDLE_CONNECTION_TTL_SEC", 180))
    REDIS_IDLE_SWEEP_INTERVAL_SEC = int(os.getenv("REDIS_IDLE_SWEEP_INTERVAL_SEC", 30))
    DEFAULT_CACHE_TTL = int(os.getenv("DEFAULT_CACHE_TTL", 60 * 10))
    S3_PRESIGN_EXPIRE_SECONDS = int(os.getenv("S3_PRESIGN_EXPIRE_SECONDS", "300"))
    NODE_FILE_UPLOAD_MAX_SIZE_BYTES = int(
        os.getenv("NODE_FILE_UPLOAD_MAX_SIZE_BYTES", str(20 * 1024 * 1024))
    )
    DISABLE_STORE: bool = os.getenv("DISABLE_STORE", "no").lower() in _TRUE_STATEMENT_TOKENS


class DASK_PARTITIONING:
    TARGET_PARTITION_MEM_MB = int(os.getenv("TARGET_PARTITION_MEM_MB", "16"))
    OVERHEAD_COEF = float(os.getenv("OVERHEAD_COEF", "1.8"))
    MIN_ROWS_PER_PART = int(os.getenv("MIN_ROWS_PER_PART", "10000"))
    MAX_PARTITIONS = int(os.getenv("MAX_PARTITIONS", "5000"))


class WS_FORWARD:
    GRPC_FORWARD_SERVICE_HOST = os.getenv("GRPC_FORWARD_SERVICE_HOST", "127.0.0.1")
    GRPC_FORWARD_SERVICE_PORT = os.getenv("GRPC_FORWARD_SERVICE_PORT", "45061")
    GRPC_FORWARD_SERVICE_URL = f"{GRPC_FORWARD_SERVICE_HOST}:{GRPC_FORWARD_SERVICE_PORT}"
    GRPC_FORWARD_SERVICE_TOKEN = os.getenv("GRPC_FORWARD_SERVICE_TOKEN", "secret-token-WS-FORWARD")
    GRPC_FORWARD_SERVICE_MAX_SEND_MESSAGE_LEN_MB = int(os.getenv("GRPC_FORWARD_SERVICE_MAX_SEND_MESSAGE_LEN_MB", "500"))
    GRPC_FORWARD_SERVICE_MAX_RECEIVE_MESSAGE_LEN_MB = int(
        os.getenv("GRPC_FORWARD_SERVICE_MAX_RECEIVE_MESSAGE_LEN_MB", "500")
    )


class INSTALLATION_MANAGER:
    INSTALLATION_MANAGER_HOST = os.getenv("INSTALLATION_MANAGER_HOST", "installation_manager")
    INSTALLATION_MANAGER_PORT = int(os.getenv("INSTALLATION_MANAGER_PORT", "8000"))
    INSTALLATION_MANAGER_URL = os.getenv(
        "INSTALLATION_MANAGER_URL",
        f"http://{INSTALLATION_MANAGER_HOST}:{INSTALLATION_MANAGER_PORT}",
    ).rstrip("/")
    REQUEST_TIMEOUT_SEC = float(os.getenv("INSTALLATION_MANAGER_REQUEST_TIMEOUT_SEC", "30"))


class SYSTEM_STATE:
    POLL_INTERVAL_SEC = float(os.getenv("SYSTEM_STATE_POLL_INTERVAL_SEC", "2"))
    RETRY_AFTER_SEC = int(os.getenv("SYSTEM_STATE_RETRY_AFTER_SEC", "3"))
    MANAGER_STALE_TIMEOUT_SEC = float(
        os.getenv("SYSTEM_STATE_MANAGER_STALE_TIMEOUT_SEC", "60")
    )
    READINESS_TIMEOUT_SEC = float(os.getenv("SYSTEM_STATE_READINESS_TIMEOUT_SEC", "300"))
    RECENT_UPDATE_WINDOW_SEC = float(
        os.getenv("SYSTEM_STATE_RECENT_UPDATE_WINDOW_SEC", "600")
    )
    STATUS_REQUEST_TIMEOUT_SEC = float(
        os.getenv("SYSTEM_STATE_STATUS_REQUEST_TIMEOUT_SEC", "5")
    )


class DCC_INTEGRATION:
    DCC_READY_STATUS_CHECK_INTERVAL = 10
    DCC_TASK_LISTEN_INTERVAL = 10


class METRICS:
    ENABLED = os.getenv("METRICS_ENABLED", "true").lower() in _TRUE_STATEMENT_TOKENS
    RUNTIME_REFRESH_SEC = int(os.getenv("METRICS_RUNTIME_REFRESH_SEC", "15"))
    DB_REFRESH_SEC = int(os.getenv("METRICS_DB_REFRESH_SEC", "60"))
