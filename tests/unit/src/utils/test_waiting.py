from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, create_engine

from src.utils import waiting


def write_release(path: Path, revision: str = "0002") -> Path:
    path.write_text(
        f"RELEASE_FORMAT_VERSION=1\nALEMBIC_REVISION={revision}\n",
        encoding="utf-8",
    )
    return path


def create_alembic_version_table(engine, revisions: list[str]) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(255))"))
        for revision in revisions:
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": revision},
            )


def test_wait_for_alembic_migrations_returns_when_revision_matches(tmp_path: Path) -> None:
    engine = create_engine("sqlite://")
    create_alembic_version_table(engine, ["0002"])
    release_path = write_release(tmp_path / "RELEASE")

    with Session(engine) as session:
        waiting.wait_for_alembic_migrations(session, release_path, timeout=0)


def test_wait_for_alembic_migrations_waits_until_revision_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = create_engine("sqlite://")
    create_alembic_version_table(engine, ["0001"])
    release_path = write_release(tmp_path / "RELEASE", "0002")
    sleeps: list[float] = []

    def apply_migration(delay: float) -> None:
        sleeps.append(delay)
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM alembic_version"))
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES ('0002')")
            )

    monkeypatch.setattr(waiting.time, "sleep", apply_migration)

    with Session(engine) as session:
        waiting.wait_for_alembic_migrations(
            session,
            release_path,
            interval=0.01,
            timeout=1,
        )

    assert sleeps == [0.01]


def test_wait_for_alembic_migrations_compares_all_version_rows(tmp_path: Path) -> None:
    engine = create_engine("sqlite://")
    create_alembic_version_table(engine, ["0001", "0002"])
    release_path = write_release(tmp_path / "RELEASE", "0002")

    with Session(engine) as session, pytest.raises(
        TimeoutError,
        match=r"\['0001', '0002'\]",
    ):
        waiting.wait_for_alembic_migrations(session, release_path, timeout=0)


def test_wait_for_alembic_migrations_times_out_when_version_table_is_missing(
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite://")
    release_path = write_release(tmp_path / "RELEASE")

    with Session(engine) as session, pytest.raises(
        TimeoutError,
        match=r"current revisions: \[\]",
    ):
        waiting.wait_for_alembic_migrations(session, release_path, timeout=0)


def test_wait_for_alembic_migrations_retries_transient_connection_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    release_path = write_release(tmp_path / "RELEASE")
    events: list[str] = []

    class FakeResult:
        def scalars(self):
            return ["0002"]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def execute(self, _statement):
            return FakeResult()

    class FakeEngine:
        url = type("Url", (), {"database": "test-db"})()
        attempts = 0

        def connect(self):
            self.attempts += 1
            if self.attempts == 1:
                raise OperationalError("SELECT", {}, RuntimeError("connection refused"))
            return FakeConnection()

        def dispose(self) -> None:
            events.append("engine.dispose")

    class FakeSession:
        engine = FakeEngine()

        def get_bind(self):
            return self.engine

    class FakeInspector:
        def has_table(self, table_name: str) -> bool:
            assert table_name == "alembic_version"
            return True

    monkeypatch.setattr(waiting, "inspect", lambda _connection: FakeInspector())
    monkeypatch.setattr(waiting.time, "sleep", lambda _delay: events.append("sleep"))

    waiting.wait_for_alembic_migrations(
        FakeSession(),
        release_path,
        interval=0.01,
        timeout=1,
    )

    assert events == ["engine.dispose", "sleep"]


@pytest.mark.parametrize(
    "content, message",
    [
        ("ALEMBIC_REVISION=0002\n", "RELEASE_FORMAT_VERSION"),
        ("RELEASE_FORMAT_VERSION=1\n", "ALEMBIC_REVISION"),
        (
            "RELEASE_FORMAT_VERSION=1\nALEMBIC_REVISION=0001\nALEMBIC_REVISION=0002\n",
            "Duplicate",
        ),
        ("RELEASE_FORMAT_VERSION=1\nALEMBIC_REVISION=${HEAD}\n", "substitutions"),
        ("RELEASE_FORMAT_VERSION=1\nALEMBIC_REVISION=feature_head\n", "invalid"),
    ],
)
def test_read_expected_alembic_revision_rejects_invalid_release(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    release_path = tmp_path / "RELEASE"
    release_path.write_text(content, encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        waiting._read_expected_alembic_revision(release_path)


def test_read_expected_alembic_revision_rejects_missing_release(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Could not read"):
        waiting._read_expected_alembic_revision(tmp_path / "RELEASE")
