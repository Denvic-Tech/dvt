from services.orchestrator import main


def test_wait_for_database_schema_checks_connectivity_before_migrations(monkeypatch) -> None:
    events: list[str] = []
    session = object()

    class FakeSessionContext:
        def __enter__(self):
            events.append("session.open")
            return session

        def __exit__(self, *_args) -> None:
            events.append("session.close")

    monkeypatch.setattr(main, "Session", lambda _engine: FakeSessionContext())
    monkeypatch.setattr(main, "wait_for_db", lambda value: events.append("database.ready"))
    monkeypatch.setattr(
        main,
        "wait_for_alembic_migrations",
        lambda value, **_kwargs: events.append("migrations.ready"),
    )

    main._wait_for_database_schema()

    assert events == [
        "session.open",
        "database.ready",
        "migrations.ready",
        "session.close",
    ]
