import asyncio

from loguru import logger as loguru_logger

from src.schemas.http.log import LogEntrySchema
from src.schemas.event import EventCallback, LogEvent
from src.logger.formatters import sink_formatter
import config


def make_websocket_sink(
        service_name: str,
        send_message_callback: EventCallback,
        loop: asyncio.AbstractEventLoop
):
    def _websocket_sink(message):
        record = message.record
        user_id = record["extra"].get("user_id")
        project_id = record["extra"].get("project_id")
        send_ws_messages = record["extra"].get("send_ws_messages", True)
        if not send_ws_messages or not user_id or not project_id:
            return

        log_entry = LogEntrySchema(
            created_at=record["time"],
            level=record["level"].name,
            service_name=service_name,
            message=record["message"],
            exception_traceback=record["extra"].get("traceback_str"),
            logger_name=record["name"],
            module=record["module"],
            function=record["function"],
            line=record["line"],
        )
        log_message = LogEvent(entry=log_entry)
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(send_message_callback(log_message, user_id=user_id, project_id=project_id), loop)

    return _websocket_sink


def add_websocket_log_sink(
        send_message_callback: EventCallback,
        loop: asyncio.AbstractEventLoop,
        level: str = "DEBUG",
):
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()

    websocket_sink = make_websocket_sink(
        send_message_callback=send_message_callback,
        service_name=config.COMMON.SERVICE_NAME,
        loop=loop,
    )
    loguru_logger.add(
        websocket_sink,
        level=level.upper(),
        enqueue=True,
        catch=True,
        format=sink_formatter
    )
    loguru_logger.info(f"Structured WebSocket log sink added with level {level.upper()}.")
