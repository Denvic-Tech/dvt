from src.infra.celery import create_celery_app

import config


def test_create_celery_app_configures_visibility_timeout(monkeypatch):
    monkeypatch.setattr(config.CELERY, "CELERY_VISIBILITY_TIMEOUT_SEC", 14_400)

    app = create_celery_app("test_celery_visibility")

    assert app.conf.broker_transport_options["visibility_timeout"] == 14_400
    assert app.conf.result_backend_transport_options["visibility_timeout"] == 14_400
    assert app.conf.visibility_timeout == 14_400
