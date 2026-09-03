def run() -> None:
    from services.task_worker.celery_app import celery_app

    from src.utils.worker_id import initialize_worker_id

    import config

    worker_id = initialize_worker_id()
    # STOP/KILL use Celery remote control through the orchestrator.  Keeping the
    # control queue out of this one-slot worker prevents a queued control task
    # from competing with a long-running pipeline task.
    queues = f"{config.CELERY.CELERY_TASKS_QUEUE},{config.CELERY.CELERY_DEPS_QUEUE}"
    celery_app.worker_main([
        "worker",
        "--hostname",
        worker_id,
        "-Q",
        queues,
    ])


if __name__ == "__main__":
    run()
