from collections.abc import Mapping

import config

from ...domain.gateways import TaskTransport


class CeleryTaskTransport(TaskTransport):
    def __init__(self, celery_app) -> None:
        self._celery_app = celery_app

    def publish(self, *, task_id: str, payload: Mapping[str, object]) -> None:
        self._celery_app.send_task(
            "task_worker.handle_task",
            args=[dict(payload)],
            queue=config.CELERY.CELERY_TASKS_QUEUE,
            task_id=task_id,
        )

    def revoke(self, *, task_id: str, terminate: bool = False) -> None:
        self._celery_app.control.revoke(task_id, terminate=terminate, signal="SIGTERM" if terminate else None)
