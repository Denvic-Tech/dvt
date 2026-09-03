from __future__ import annotations

from src.logger import db_sink


def test_add_db_log_sink_uses_explicit_engine_and_service_name(monkeypatch):
    created_sinks: list[object] = []
    add_calls: list[dict[str, object]] = []
    info_messages: list[str] = []

    class _FakeSink:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created_sinks.append(self)

    def _fake_add(sink, **kwargs):
        add_calls.append({"sink": sink, **kwargs})
        return 37

    def _fake_info(message):
        info_messages.append(message)

    previous_sink = db_sink.DB_SINK
    previous_handler_id = db_sink.DB_SINK_HANDLER_ID

    monkeypatch.setattr(db_sink, "BatchedDBSink", _FakeSink)
    monkeypatch.setattr(db_sink.loguru_logger, "add", _fake_add)
    monkeypatch.setattr(db_sink.loguru_logger, "info", _fake_info)

    fake_loop = object()
    fake_engine = object()

    try:
        db_sink.add_db_log_sink(
            loop=fake_loop,
            level="debug",
            engine=fake_engine,
            service_name="gateway-test",
        )

        assert len(created_sinks) == 1
        assert created_sinks[0].kwargs["engine"] is fake_engine
        assert created_sinks[0].kwargs["service_name"] == "gateway-test"
        assert created_sinks[0].kwargs["loop"] is fake_loop
        assert db_sink.DB_SINK is created_sinks[0]
        assert db_sink.DB_SINK_HANDLER_ID == 37
        assert add_calls == [
            {
                "sink": created_sinks[0],
                "level": "DEBUG",
                "enqueue": True,
                "catch": True,
                "format": db_sink.sink_formatter,
            }
        ]
        assert info_messages == [
            "Structured DB log sink added with level DEBUG (async, no WAL)."
        ]
    finally:
        db_sink.DB_SINK = previous_sink
        db_sink.DB_SINK_HANDLER_ID = previous_handler_id


def test_add_db_log_sink_uses_default_service_name(monkeypatch):
    created_sinks: list[object] = []

    class _FakeSink:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created_sinks.append(self)

    previous_sink = db_sink.DB_SINK
    previous_handler_id = db_sink.DB_SINK_HANDLER_ID

    monkeypatch.setattr(db_sink, "BatchedDBSink", _FakeSink)
    monkeypatch.setattr(db_sink.loguru_logger, "add", lambda *_args, **_kwargs: 11)
    monkeypatch.setattr(db_sink.loguru_logger, "info", lambda *_args, **_kwargs: None)

    try:
        db_sink.add_db_log_sink(
            loop=object(),
            level="info",
            engine=object(),
        )

        assert len(created_sinks) == 1
        assert created_sinks[0].kwargs["service_name"] == db_sink.config.COMMON.SERVICE_NAME
    finally:
        db_sink.DB_SINK = previous_sink
        db_sink.DB_SINK_HANDLER_ID = previous_handler_id
