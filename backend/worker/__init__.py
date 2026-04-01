"""
Celery Application

Configures the Celery app for background task processing and scheduled jobs.
Uses the broker URL from settings (typically Redis).

Usage:
    Start worker:   celery -A backend.worker.celery_app worker --loglevel=info
    Start beat:     celery -A backend.worker.celery_app beat --loglevel=info
    Start both:     celery -A backend.worker.celery_app worker --beat --loglevel=info

Environment variables required:
    CELERY_BROKER_URL     — Redis URL e.g. redis://localhost:6379/0
    CELERY_RESULT_BACKEND — Redis URL e.g. redis://localhost:6379/1 (optional)
"""

from celery import Celery
from celery.schedules import crontab

from backend.config.settings import get_settings

settings = get_settings()

# Fall back to in-process task execution if broker not configured.
# In production, always set CELERY_BROKER_URL.
_broker = settings.celery_broker_url or "memory://"
_backend = settings.celery_result_backend or "cache+memory://"

celery_app = Celery(
    "finops_orchestrator",
    broker=_broker,
    backend=_backend,
    include=["backend.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Beat schedule: run nightly optimization signal ingestion at 2 AM UTC
    beat_schedule={
        "nightly-optimization-ingestion": {
            "task": "backend.worker.tasks.ingest_optimization_signals",
            "schedule": crontab(hour=2, minute=0),  # 2:00 AM UTC every day
            "options": {"expires": 3600},  # Expire if not picked up within 1 hour
        },
    },
    # Retry failed tasks up to 3 times with exponential backoff
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)
