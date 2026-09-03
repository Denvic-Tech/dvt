from services.orchestrator.celery_app import celery_app

import config


def test_orchestrator_uses_configured_visibility_timeout() -> None:
    timeout = config.CELERY.CELERY_VISIBILITY_TIMEOUT_SEC

    assert celery_app.conf.broker_transport_options["visibility_timeout"] == timeout
    assert celery_app.conf.result_backend_transport_options["visibility_timeout"] == timeout
    assert celery_app.conf.visibility_timeout == timeout
