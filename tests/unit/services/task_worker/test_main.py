from types import SimpleNamespace

from services.task_worker import main


def test_run_initializes_worker_identity_and_uses_it_as_celery_hostname(monkeypatch):
    calls: list[list[str]] = []
    celery_app = SimpleNamespace(worker_main=calls.append)

    monkeypatch.setattr(
        "src.utils.worker_id.initialize_worker_id",
        lambda: "task-worker-host-1-instance",
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "services.task_worker.celery_app",
        SimpleNamespace(celery_app=celery_app),
    )

    main.run()

    assert calls == [[
        "worker",
        "--hostname",
        "task-worker-host-1-instance",
        "-Q",
        "tasks.worker,tasks.deps",
    ]]
