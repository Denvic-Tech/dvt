import asyncio
import contextlib
import re
import time
from collections.abc import Iterable
from pathlib import Path

from kafka.admin import ConfigResource, ConfigResourceType, KafkaAdminClient
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from src.logger import logger
from src.utils.kafka_tools import parse_kafka_config_response

TRANSIENT_SUBSTRINGS: tuple[str, ...] = tuple(s.lower() for s in [
    "connection refused",
    "could not connect to server",
    "connect timed out",
    "timeout expired",
    "could not translate host name",
    "temporary failure in name resolution",
    "name or service not known",
    "no route to host",
    "network is unreachable",
    "server closed the connection unexpectedly",
    "the database system is starting up",
    "system is starting up",
    "connection failed",
    "could not receive data from server",
    "could not send ssl negotiation packet",
    "ssl handshake failure",
    "socket is not connected",
    "connection reset by peer",
    "target machine actively refused",
])

RELEASE_FORMAT_VERSION = "1"
RELEASE_FORMAT_KEY = "RELEASE_FORMAT_VERSION"
ALEMBIC_REVISION_KEY = "ALEMBIC_REVISION"

_RELEASE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_REVISION_PATTERN = re.compile(r"^\d{4}$")
_FORBIDDEN_RELEASE_TOKENS = ("${", "$(", "`")


def _get_engine(session: Session) -> Engine:
    bind = session.get_bind()
    if hasattr(bind, "engine"):
        return bind.engine
    return bind


def _read_expected_alembic_revision(release_path: str | Path) -> str:
    path = Path(release_path)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Could not read release metadata from '{path}': {exc}") from exc

    values: dict[str, str] = {}
    for line_number, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export ") or "=" not in stripped:
            raise RuntimeError(
                f"Invalid release metadata at {path}:{line_number}: "
                "expected an unquoted KEY=VALUE assignment"
            )

        key, value = stripped.split("=", 1)
        if not _RELEASE_KEY_PATTERN.fullmatch(key):
            raise RuntimeError(f"Invalid release metadata key '{key}' at {path}:{line_number}")
        if key in values:
            raise RuntimeError(f"Duplicate release metadata key '{key}' at {path}:{line_number}")
        if any(token in value for token in _FORBIDDEN_RELEASE_TOKENS):
            raise RuntimeError(f"Shell substitutions are not allowed at {path}:{line_number}")
        if "'" in value or '"' in value:
            raise RuntimeError(
                f"Quoted release metadata values are not supported at {path}:{line_number}"
            )
        values[key] = value

    format_version = values.get(RELEASE_FORMAT_KEY)
    if format_version != RELEASE_FORMAT_VERSION:
        raise RuntimeError(
            f"Unsupported or missing {RELEASE_FORMAT_KEY} in '{path}': {format_version!r}"
        )

    revision = values.get(ALEMBIC_REVISION_KEY)
    if revision is None or not _REVISION_PATTERN.fullmatch(revision):
        raise RuntimeError(
            f"Missing or invalid {ALEMBIC_REVISION_KEY} in release metadata '{path}'"
        )
    return revision


def _is_transient_db_error(e: Exception, extra_markers: Iterable[str] = ()) -> bool:
    msg = str(e).lower()
    for key in TRANSIENT_SUBSTRINGS + tuple(s.lower() for s in extra_markers):
        if key in msg:
            return True

    return bool(isinstance(e, OperationalError))


def wait_for_db(
    session: Session,
    interval: float = 1.0,
    timeout: float = 60.0,
    extra_retry_markers: Iterable[str] = (),
) -> None:
    """
    Блокирующе ждём доступности БД. Безопасно вызывать в sync-части lifespan.
    Пробуем создать connect() на уровне engine, выполняем SELECT 1 и закрываем.
    При неудаче делаем dispose(), логируем и спим.
    """
    engine = _get_engine(session)

    deadline = time.time() + timeout
    db_url = str(engine.url)
    db_name = engine.url.database

    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info(f"Database '{db_name}' is available ({db_url})")
            return

        except Exception as e:
            last_err = e
            if _is_transient_db_error(e, extra_retry_markers):
                remaining = max(0.0, deadline - time.time())
                if remaining <= 0:
                    break
                logger.info(
                    f"Waiting for the database '{db_name}' to start "
                    f"(retry in {interval:.1f}s, left ~{remaining:.1f}s): {e}"
                )
                with contextlib.suppress(Exception):
                    engine.dispose()


                time.sleep(interval)
                continue

            raise

    logger.error(f"Database '{db_name}' did not become available within {timeout:.1f}s; last error: {last_err}")
    raise TimeoutError(
        f"Database '{db_name}' did not become available within the timeout period"
    )


def wait_for_alembic_migrations(
    session: Session,
    release_path: str | Path,
    interval: float = 1.0,
    timeout: float = 300.0,
    extra_retry_markers: Iterable[str] = (),
) -> None:
    """Wait until the database Alembic revision matches the current release."""
    if interval <= 0:
        raise ValueError("interval must be greater than zero")
    if timeout < 0:
        raise ValueError("timeout must be greater than or equal to zero")

    expected_revision = _read_expected_alembic_revision(release_path)
    expected_revisions = {expected_revision}
    engine = _get_engine(session)
    db_name = engine.url.database
    deadline = time.monotonic() + timeout
    current_revisions: set[str] = set()
    last_error: Exception | None = None

    while True:
        try:
            with engine.connect() as connection:
                if inspect(connection).has_table("alembic_version"):
                    current_revisions = set(
                        connection.execute(
                            text("SELECT version_num FROM alembic_version")
                        ).scalars()
                    )
                else:
                    current_revisions = set()
            last_error = None

            if current_revisions == expected_revisions:
                logger.info(
                    f"Database '{db_name}' migrations are ready "
                    f"(revision '{expected_revision}')"
                )
                return
        except Exception as exc:
            if not _is_transient_db_error(exc, extra_retry_markers):
                raise
            last_error = exc
            current_revisions = set()
            with contextlib.suppress(Exception):
                engine.dispose()

        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0:
            break

        status = (
            f"last error: {last_error}"
            if last_error is not None
            else f"current revisions: {sorted(current_revisions)}"
        )
        logger.info(
            f"Waiting for database '{db_name}' migrations to reach "
            f"revision '{expected_revision}' "
            f"(retry in {interval:.1f}s, left ~{remaining:.1f}s; {status})"
        )
        time.sleep(min(interval, remaining))

    details = (
        f"last error: {last_error}"
        if last_error is not None
        else f"current revisions: {sorted(current_revisions)}"
    )
    raise TimeoutError(
        f"Database '{db_name}' did not reach Alembic revision "
        f"'{expected_revision}' within {timeout:.1f}s; {details}"
    )


class TopicWaitError(Exception):
    pass


async def wait_for_topic(
    broker: str,
    topic_name: str,
    timeout: float | None,
    required_config: dict[str, str],
    check_interval: float = 2.0,
):
    """
    Ждет появления Kafka топика и применения нужных параметров конфигурации.
    Если timeout=None — ждать бесконечно.
    """

    if timeout is not None:
        deadline = time.time() + timeout
        infinite = False
    else:
        deadline = None
        infinite = True

    logger.info(f"[Kafka] Waiting for topic '{topic_name}' to be created...")

    while infinite or time.time() < deadline:
        try:
            admin = KafkaAdminClient(bootstrap_servers=broker, request_timeout_ms=5000)

            topics = admin.list_topics()
            if topic_name not in topics:
                logger.info(f"[Kafka] Topic '{topic_name}' not found yet...")
                await asyncio.sleep(check_interval)
                continue

            logger.info(f"[Kafka] Topic '{topic_name}' found. Checking config...")

            resource = ConfigResource(
                resource_type=ConfigResourceType.TOPIC,
                name=topic_name,
            )

            response = admin.describe_configs([resource])
            actual = parse_kafka_config_response(response)

            all_ok = True
            for key, expected_value in required_config.items():
                actual_value = actual.get(key)
                if actual_value != str(expected_value):
                    logger.info(
                        f"[Kafka] Topic config mismatch: {key}={actual_value}, expected={expected_value}"
                    )
                    all_ok = False

            if all_ok:
                logger.info(f"[Kafka] Topic '{topic_name}' is ready with correct config.")
                return

        except Exception as e:
            logger.warning(f"[Kafka] Error checking topic: {e}")

        await asyncio.sleep(check_interval)

    raise TopicWaitError(
        f"Timeout while waiting for topic '{topic_name}' and its config."
    )

