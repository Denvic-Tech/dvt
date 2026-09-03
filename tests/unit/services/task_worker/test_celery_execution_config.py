from services.task_worker.celery_app import celery_app


def test_pipeline_worker_has_exactly_one_execution_slot_without_lost_worker_redelivery():
    assert celery_app.conf.worker_pool == "prefork"
    assert celery_app.conf.worker_concurrency == 1
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.worker_disable_prefetch is True
    assert celery_app.conf.task_reject_on_worker_lost is False
    assert celery_app.conf.worker_max_tasks_per_child is None
