"""
Health Check Helpers — Supply Chain v1.0
Standardized health endpoints + HealthMonitor for polling all agents.
"""

import time
import json
import logging
import threading
from typing import Optional

import httpx

from shared.config import ALL_AGENT_URLS, REDIS_URL

log = logging.getLogger("health")

_start_time = time.time()


def build_health_response(
    agent_name: str,
    version: str = "1.0.0",
    db_connected: bool = True,
    dependencies: dict = None,
    extra: dict = None,
) -> dict:
    """Build a standardized health check JSON response."""
    response = {
        "status": "ok",
        "agent": agent_name,
        "version": version,
        "uptime_s": round(time.time() - _start_time, 1),
        "db_connected": db_connected,
    }
    if dependencies:
        response["dependencies"] = dependencies
    if extra:
        response.update(extra)
    return response


def check_db_connection(db_config: dict) -> bool:
    """Check if PostgreSQL is reachable."""
    try:
        import psycopg2
        conn = psycopg2.connect(**db_config, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


def check_agent_health(url: str, timeout: int = 3) -> dict:
    """Ping a single agent's /health endpoint."""
    start = time.time()
    try:
        r = httpx.get(f"{url}/health", timeout=timeout)
        latency = round((time.time() - start) * 1000, 2)
        data = r.json()
        data["latency_ms"] = latency
        data["reachable"] = True
        return data
    except Exception as e:
        latency = round((time.time() - start) * 1000, 2)
        return {
            "status": "unreachable",
            "reachable": False,
            "latency_ms": latency,
            "error": str(e),
        }


class HealthMonitor:
    """
    Polls all agents every N seconds and stores status in Redis.
    Used by the API gateway to serve /api/agents/health.
    """

    def __init__(self, poll_interval: int = 30):
        self.poll_interval = poll_interval
        self._status: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._redis = None
        self._running = False

    def start(self):
        """Start background polling thread."""
        try:
            import redis
            self._redis = redis.from_url(REDIS_URL, decode_responses=True)
            self._redis.ping()
        except Exception as e:
            log.warning(f"Redis unavailable for health monitor: {e}")
            self._redis = None

        self._running = True
        t = threading.Thread(target=self._poll_loop, daemon=True)
        t.start()
        log.info(f"HealthMonitor started — polling every {self.poll_interval}s")

    def stop(self):
        self._running = False

    def _poll_loop(self):
        while self._running:
            self._poll_all()
            time.sleep(self.poll_interval)

    def _poll_all(self):
        status = {}
        for name, url in ALL_AGENT_URLS.items():
            health = check_agent_health(url)
            health["name"] = name
            health["url"] = url
            status[name] = health

        with self._lock:
            self._status = status

        if self._redis:
            try:
                self._redis.set(
                    "agent_health",
                    json.dumps(status, default=str),
                    ex=self.poll_interval * 3,
                )
            except Exception as e:
                log.warning(f"Failed to store health in Redis: {e}")

    def get_status(self) -> dict:
        """Get latest health status for all agents."""
        with self._lock:
            return dict(self._status)

    def get_agent_status(self, name: str) -> Optional[dict]:
        """Get health status for a specific agent."""
        with self._lock:
            return self._status.get(name)
