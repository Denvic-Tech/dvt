from src.infra.celery import create_celery_app

celery_app = create_celery_app("orchestrator_celery")
