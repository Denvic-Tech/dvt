from celery import Celery

import config


def create_celery_app(name: str) -> Celery:
    app = Celery(
        name,
        broker=config.CELERY.CELERY_BROKER_URL,
        backend=config.CELERY.CELERY_RESULT_BACKEND,
    )

    visibility_timeout = config.CELERY.CELERY_VISIBILITY_TIMEOUT_SEC
    broker_transport_options = dict(app.conf.broker_transport_options or {})
    result_backend_transport_options = dict(app.conf.result_backend_transport_options or {})
    broker_transport_options["visibility_timeout"] = visibility_timeout
    result_backend_transport_options["visibility_timeout"] = visibility_timeout

    app.conf.update(
        broker_transport_options=broker_transport_options,
        result_backend_transport_options=result_backend_transport_options,
        visibility_timeout=visibility_timeout,
    )
    return app
