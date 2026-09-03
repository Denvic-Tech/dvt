"""Хранилище задач: одна активная установка/обновление за раз."""

from __future__ import annotations

import threading

from ..domain.models import Job, JobState


class JobAlreadyRunning(RuntimeError):
    pass


class InMemoryJobStore:
    def __init__(self) -> None:
        self._job: Job | None = None
        self._lock = threading.Lock()

    def current(self) -> Job | None:
        return self._job

    def start(self, job: Job) -> None:
        with self._lock:
            if self._job is not None and self._job.state == JobState.RUNNING:
                raise JobAlreadyRunning("Установка или обновление уже выполняется")
            self._job = job
