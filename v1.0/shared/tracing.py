"""
LangSmith Tracing — Supply Chain v1.0
Wrappers for tracing all LLM + A2A calls in LangSmith.
"""

import time
import logging
import httpx
from langsmith import traceable

log = logging.getLogger("tracing")


@traceable(name="a2a_call")
def traced_a2a_call(url: str, payload: dict, timeout: int = 10) -> tuple[dict, float]:
    """
    Make a traced A2A HTTP call. Returns (response_dict, latency_ms).
    Every call appears as a child span in LangSmith.
    """
    start = time.time()
    try:
        r = httpx.post(f"{url}/a2a", json=payload, timeout=timeout)
        latency = round((time.time() - start) * 1000, 2)
        return r.json(), latency
    except Exception as e:
        latency = round((time.time() - start) * 1000, 2)
        log.warning(f"A2A call to {url} failed ({latency}ms): {e}")
        return {"status": "error", "message": str(e)}, latency


@traceable(name="http_get")
def traced_http_get(url: str, timeout: int = 5) -> tuple[dict, float]:
    """Traced HTTP GET request. Returns (response_dict, latency_ms)."""
    start = time.time()
    try:
        r = httpx.get(url, timeout=timeout)
        latency = round((time.time() - start) * 1000, 2)
        return r.json(), latency
    except Exception as e:
        latency = round((time.time() - start) * 1000, 2)
        log.warning(f"HTTP GET {url} failed ({latency}ms): {e}")
        return {"status": "error", "message": str(e)}, latency
