from datetime import timezone
from typing import Any, Callable, ContextManager, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_ERROR, JobExecutionEvent
from apscheduler.triggers.cron import CronTrigger
from apscheduler.job import Job

from src.logger import logger
from src import exceptions as exc


LockFactory = Callable[[], ContextManager[Any]]


class BackgroundSchedulerManager:
    """
    Менеджер для работы с фоновым планировщиком задач
    """
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.scheduler.add_listener(self.job_error_listener, EVENT_JOB_ERROR)
        self.scheduler.start()

    @staticmethod
    def job_error_listener(event: JobExecutionEvent):
        """
        Обработчик ошибок в задачах
        """
        if event.exception:
            logger.error(f"Error in scheduled task ID={event.job_id}: {event.exception}")
            if event.traceback:
                logger.debug(f"Traceback:\n{event.traceback}")

    def schedule_job(
        self,
        func: Callable[..., Any],
        *,
        job_id: Optional[str] = None,
        cron: str,
        jitter: Optional[int] = None,
        replace_existing: bool = True,
        lock_ctx: Optional[LockFactory] = None,
    ) -> Job:
        wrapped = self._wrap(func, lock_ctx)

        job = self.scheduler.add_job(
            wrapped,
            trigger=CronTrigger.from_crontab(cron),
            id=job_id,
            replace_existing=replace_existing,
            jitter=jitter,
        )
        logger.info("[scheduler] - Job added ID={} trigger={}", job.id, cron)
        logger.info("[scheduler] - Next run at {}", job.next_run_time.astimezone(timezone.utc).isoformat())
        return job

    def remove_job(self, job_id: str) -> None:
        self.scheduler.remove_job(job_id)

    def pause_job(self, job_id: str) -> None:
        self.scheduler.pause_job(job_id)

    def resume_job(self, job_id: str) -> None:
        self.scheduler.resume_job(job_id)

    def shutdown(self, wait: bool = False) -> None:
        """
        Остановить планировщик
        """
        logger.info("Shutting down BackgroundScheduler")
        self.scheduler.shutdown(wait=wait)

    def _wrap(
            self,
            func: Callable[..., Any],
            lock_ctx: Optional[Callable[[], ContextManager[None]]],
    ) -> Callable[..., Any]:
        def _runner(*a, **k) -> Optional[Any]:
            try:
                if lock_ctx:
                    with lock_ctx():
                        return func(*a, **k)
                return func(*a, **k)
            except exc.SkipBackgroundRun as e:
                logger.info("[scheduler] - Skipped run: {}", e)
            except Exception as e:
                logger.exception("[scheduler] - Job error: {}", e)

        return _runner
