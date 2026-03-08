"""
Celery Tasks — Supply Chain v1.0
Async task definitions for the supply chain pipeline.
Each task has retry logic and error handling.
"""

import os
import sys
import json
import time
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from celery_app import celery_app
from shared.config import (
    PRICING_AGENT_URL, INVENTORY_AGENT_URL, ORDER_AGENT_URL,
    NOTIFICATION_AGENT_URL, FINANCE_AGENT_URL, REDIS_URL
)
from shared.tracing import traced_a2a_call

log = logging.getLogger("celery-tasks")

# Redis for WebSocket event publishing
try:
    import redis
    _redis = redis.from_url(REDIS_URL, decode_responses=True)
except:
    _redis = None


def publish_event(event: dict):
    """Publish pipeline event to Redis for WebSocket consumption."""
    if _redis:
        try:
            _redis.publish("pipeline_events", json.dumps(event))
            _redis.lpush("pipeline_event_log", json.dumps(event))
            _redis.ltrim("pipeline_event_log", 0, 199)  # Keep last 200 events
        except Exception as e:
            log.warning(f"Redis publish failed: {e}")


@celery_app.task(bind=True, name="pipeline.sync_prices",
                 max_retries=3, default_retry_delay=5)
def sync_prices(self):
    """Async price sync via Pricing Agent."""
    start = time.time()
    try:
        publish_event({"step": "price_sync", "status": "started", "task_id": self.request.id})

        result, latency = traced_a2a_call(PRICING_AGENT_URL, {"task": "sync_prices"})
        updates = result.get("updates", [])

        publish_event({
            "step": "price_sync", "status": "complete",
            "updates": len(updates), "ms": latency,
            "task_id": self.request.id
        })
        return {"status": "success", "updates": updates, "latency_ms": latency}

    except Exception as e:
        publish_event({"step": "price_sync", "status": "error", "error": str(e)})
        self.retry(exc=e)


@celery_app.task(bind=True, name="pipeline.check_inventory",
                 max_retries=2, default_retry_delay=5)
def check_inventory(self):
    """Check inventory levels via Inventory Agent."""
    start = time.time()
    try:
        publish_event({"step": "inventory_check", "status": "started", "task_id": self.request.id})

        result, latency = traced_a2a_call(INVENTORY_AGENT_URL, {"task": "get_inventory"})

        publish_event({
            "step": "inventory_check", "status": "complete",
            "products": len(result.get("products", [])), "ms": latency,
            "task_id": self.request.id
        })
        return result

    except Exception as e:
        publish_event({"step": "inventory_check", "status": "error", "error": str(e)})
        self.retry(exc=e)


@celery_app.task(bind=True, name="pipeline.run_supplier_bidding",
                 max_retries=3, default_retry_delay=10)
def run_supplier_bidding(self, product, quantity, base_price):
    """Run supplier bidding via Inventory Agent's check_and_restock."""
    start = time.time()
    try:
        publish_event({
            "step": "supplier_bidding", "status": "started",
            "product": product, "task_id": self.request.id
        })

        result, latency = traced_a2a_call(
            INVENTORY_AGENT_URL,
            {"task": "check_and_restock"}
        )

        restocked = result.get("restocked", [])
        publish_event({
            "step": "supplier_bidding", "status": "complete",
            "restocked": len(restocked), "ms": latency,
            "task_id": self.request.id
        })
        return result

    except Exception as e:
        publish_event({"step": "supplier_bidding", "status": "error", "error": str(e)})
        self.retry(exc=e)


@celery_app.task(bind=True, name="pipeline.send_notification",
                 max_retries=5, default_retry_delay=30)
def send_notification(self, event_type, product, details):
    """Send notification email via Notification Agent."""
    try:
        publish_event({
            "step": "notification", "status": "started",
            "event_type": event_type, "product": product,
            "task_id": self.request.id
        })

        result, latency = traced_a2a_call(NOTIFICATION_AGENT_URL, {
            "task": "send_alert",
            "event_type": event_type,
            "product": product,
            "details": details,
        })

        publish_event({
            "step": "notification", "status": "complete",
            "event_type": event_type, "ms": latency,
            "task_id": self.request.id
        })
        return result

    except Exception as e:
        publish_event({"step": "notification", "status": "error", "error": str(e)})
        self.retry(exc=e)


@celery_app.task(bind=True, name="pipeline.run_full_pipeline",
                 max_retries=1, default_retry_delay=10)
def run_full_pipeline(self):
    """
    Orchestrate the full supply chain pipeline:
    1. Sync prices
    2. Check and restock (which internally does bidding + finance approval + ordering)
    """
    pipeline_id = self.request.id
    start = time.time()

    try:
        publish_event({
            "step": "pipeline", "status": "started",
            "pipeline_id": pipeline_id
        })

        # Step 1: Sync prices
        price_result, price_ms = traced_a2a_call(PRICING_AGENT_URL, {"task": "sync_prices"})
        publish_event({
            "step": "price_sync", "status": "complete",
            "updates": len(price_result.get("updates", [])), "ms": price_ms,
            "pipeline_id": pipeline_id
        })

        # Step 2: Check and restock
        restock_result, restock_ms = traced_a2a_call(
            INVENTORY_AGENT_URL,
            {"task": "check_and_restock"},
            timeout=60
        )

        restocked = restock_result.get("restocked", [])
        for item in restocked:
            publish_event({
                "step": "order_confirmed",
                "product": item.get("product"),
                "supplier": item.get("supplier"),
                "order_id": item.get("order_id"),
                "pipeline_id": pipeline_id
            })

        total_ms = round((time.time() - start) * 1000, 2)
        publish_event({
            "step": "pipeline", "status": "complete",
            "total_ms": total_ms,
            "restocked": len(restocked),
            "pipeline_id": pipeline_id
        })

        return {
            "status": "success",
            "pipeline_id": pipeline_id,
            "price_updates": price_result.get("updates", []),
            "restocked": restocked,
            "total_ms": total_ms,
        }

    except Exception as e:
        publish_event({
            "step": "pipeline", "status": "error",
            "error": str(e), "pipeline_id": pipeline_id
        })
        raise
