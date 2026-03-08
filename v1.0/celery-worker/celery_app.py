"""
Celery App Configuration — Supply Chain v1.0
Redis as broker and result backend.
"""

import os
import sys
from celery import Celery
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

celery_app = Celery(
    "supply_chain",
    broker=f"{REDIS_URL}/0",
    backend=f"{REDIS_URL}/1",
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["celery-worker"])
