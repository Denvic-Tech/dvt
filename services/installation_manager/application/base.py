"""Общая механика use case'ов: выполнение шагов job'а."""

from __future__ import annotations

from collections.abc import Callable

from ..domain.models import Job, StepStatus
from ..logger import logger


class StepError(RuntimeError):
    pass


def run_step(job: Job, step_id: str, title: str, fn: Callable[[], str | None]) -> None:
    """Выполняет один шаг job'а с обновлением статуса и логированием."""
    job.set_step(step_id, StepStatus.RUNNING)
    job.log(f"⚙️ {title}...")
    try:
        detail = fn() or ""
        job.set_step(step_id, StepStatus.OK, detail)
    except StepError as exc:
        job.set_step(step_id, StepStatus.FAILED, str(exc))
        job.log(f"❌ {exc}")
        raise
    except Exception as exc:
        logger.exception("Шаг %s завершился ошибкой", step_id)
        job.set_step(step_id, StepStatus.FAILED, str(exc))
        job.log(f"❌ {exc}")
        raise StepError(f"{title}: {exc}") from exc
