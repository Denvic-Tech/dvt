import logging
from types import FrameType
from typing import cast, TYPE_CHECKING

if TYPE_CHECKING:
    from loguru._logger import Logger


class InterceptHandler(logging.Handler):
    """Logs to loguru from Python logging module"""

    def __init__(self, logger: "Logger", level=logging.NOTSET):
        super().__init__(level=level)
        self.logger = logger

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = self.logger.level(record.levelname).name
        except ValueError:
            level = str(record.levelno)

        frame, depth = logging.currentframe(), 1
        while frame.f_code.co_filename in (logging.__file__, __file__):  # noqa: WPS609
            frame = cast(FrameType, frame.f_back)
            depth += 1
        logger_with_opts = self.logger.opt(depth=depth, exception=record.exc_info)
        try:
            logger_with_opts.log(level, "{}", record.getMessage())
        except Exception as e:
            safe_msg = getattr(record, 'msg', None) or str(record)
            logger_with_opts.warning(
                "Exception logging the following native logger message: {}, {!r}",
                safe_msg,
                e
            )
