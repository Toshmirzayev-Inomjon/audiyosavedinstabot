from __future__ import annotations

from celery import Celery

from bot.config import settings

celery_app = Celery(
    "media_super_app",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["bot.tasks.media_tasks"],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
)
