"""
Celery tasks for background MCQ generation. Use when Redis is available and queue is preferred.
"""
import logging
import uuid

from app.jobs.tasks import run_generation

logger = logging.getLogger(__name__)


def run_generation_task(test_id: str, doc_id: str, user_id: str) -> None:
    """Celery task: delegate to run_generation (same logic as BackgroundTasks)."""
    run_generation(
        uuid.UUID(test_id),
        uuid.UUID(doc_id),
        uuid.UUID(user_id),
    )


# Bind to Celery app when present
try:
    from app.celery_app import celery_app

    @celery_app.task(bind=True)
    def run_mcq_generation(self, test_id: str, doc_id: str, user_id: str) -> None:
        run_generation_task(test_id, doc_id, user_id)
except Exception as e:
    logger.debug("Celery not configured: %s", e)
