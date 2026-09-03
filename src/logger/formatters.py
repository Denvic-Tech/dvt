import traceback
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import config

if TYPE_CHECKING:
    from loguru import Record


def format_concise_traceback(record: "Record") -> Optional[str]:
    """
    Форматирует traceback, оставляя релевантные строки из кода проекта
    и обрезая его до максимальной длины, если он слишком большой.
    """
    if not record["exception"]:
        return None

    exc_type, exc_value, exc_traceback = record["exception"]

    full_trace = traceback.extract_tb(exc_traceback)

    project_root = config.PROJECT.ROOT_DIR.resolve()
    venv_path = project_root / ".venv"

    filtered_frames = []
    for frame in full_trace:
        try:
            frame_path = Path(frame.filename).resolve()
            is_in_project = project_root in frame_path.parents or project_root == frame_path
            is_in_venv = venv_path.exists() and (venv_path in frame_path.parents or venv_path == frame_path)
            if is_in_project and not is_in_venv:
                filtered_frames.append(frame)

        except Exception:
            filtered_frames.append(frame)

    frames_to_format = filtered_frames if filtered_frames else full_trace

    max_frames = config.LOGGING.LOG_TRACEBACK_MAX_LINES
    is_truncated = False
    if len(frames_to_format) > max_frames:
        frames_to_format = frames_to_format[-max_frames:]
        is_truncated = True

    final_lines = ["Traceback (most recent call last):\n"]
    if is_truncated:
        final_lines.append("  ... (traceback truncated) ...\n")

    final_lines.extend(traceback.format_list(frames_to_format))
    final_lines.extend(traceback.format_exception_only(exc_type, exc_value))

    return "".join(final_lines)


def sink_formatter(record: "Record"):
    """
    Подготавливает запись для асинхронных sink'ов, сохраняя traceback в extra.
    """
    extra = record["extra"]
    has_traceback_in_extra = bool(extra.get("traceback_str"))

    if record["exception"] and not has_traceback_in_extra:
        extra["traceback_str"] = format_concise_traceback(record)
    elif "traceback_str" not in extra:
        extra["traceback_str"] = None

    return "{message}"
