"""
Celery app for background generation. Use when concurrency or long jobs need a queue.
Requires Redis: celery_broker_url and celery_result_backend in config.
"""
from celery import Celery

from app.config import settings

broker = getattr(settings, "celery_broker_url", "redis://localhost:6379/0")
backend = getattr(settings, "celery_result_backend", "redis://localhost:6379/0")

celery_app = Celery(
    "upsc_test_engine",
    broker=broker,
    backend=backend,
    include=["app.jobs.celery_tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=settings.max_generation_time_seconds + 60,
)
