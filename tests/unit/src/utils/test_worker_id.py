from src.utils import worker_id


def test_initialize_worker_id_creates_new_internal_process_identity(monkeypatch):
    monkeypatch.setattr(worker_id.socket, "gethostname", lambda: "host-1")
    monkeypatch.setenv(worker_id._INTERNAL_WORKER_ID_ENV, "externally-provided-value")
    worker_id.get_worker_id.cache_clear()

    generated_id = worker_id.initialize_worker_id()

    assert generated_id.startswith("task-worker-host-1-")
    assert generated_id != "externally-provided-value"
    assert worker_id.get_worker_id() == generated_id


def test_get_worker_id_uses_identity_inherited_by_celery_child(monkeypatch):
    monkeypatch.setenv(worker_id._INTERNAL_WORKER_ID_ENV, "task-worker-host-1-instance")
    worker_id.get_worker_id.cache_clear()

    assert worker_id.get_worker_id() == "task-worker-host-1-instance"
