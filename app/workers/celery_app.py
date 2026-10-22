from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "agentfoundry",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_track_started=True,
    task_time_limit=600,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
