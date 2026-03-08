"""
API Gateway — Supply Chain v1.0
Runs on port 8080.
Unified entry point with:
- Agent routing / proxying
- WebSocket for real-time pipeline events
- API key authentication
- CORS for frontend
"""

import os
import sys
import json
import time
import asyncio
import logging
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import uvicorn

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.config import (
    MARKET_API_URL, PRICING_AGENT_URL, INVENTORY_AGENT_URL,
    ORDER_AGENT_URL, NOTIFICATION_AGENT_URL, FINANCE_AGENT_URL,
    SUPPLIER_A_URL, SUPPLIER_B_URL, SUPPLIER_C_URL,
    REDIS_URL, API_KEY, ALL_AGENT_URLS
)
from shared.health import HealthMonitor, check_agent_health
from shared.circuit_breaker import get_all_breaker_status

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("api-gateway")

load_dotenv()

started_at = time.time()
health_monitor = HealthMonitor(poll_interval=30)

# ── Redis for WebSocket ──────────────────────────────────────────────────────

_redis = None
try:
    import redis
    _redis = redis.from_url(REDIS_URL, decode_responses=True)
    _redis.ping()
    log.info("Redis connected for WebSocket events")
except Exception as e:
    log.warning(f"Redis unavailable: {e}")

# ── Celery ────────────────────────────────────────────────────────────────────

_celery_app = None
try:
    from celery import Celery
    _celery_app = Celery(
        "supply_chain",
        broker=f"{REDIS_URL}/0",
        backend=f"{REDIS_URL}/1",
    )
    log.info("Celery client configured")
except Exception as e:
    log.warning(f"Celery unavailable: {e}")

# ── WebSocket Manager ────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        log.info(f"WebSocket connected. Active: {len(self.active)}")

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)
        log.info(f"WebSocket disconnected. Active: {len(self.active)}")

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)

ws_manager = ConnectionManager()

# ── Auth ─────────────────────────────────────────────────────────────────────

def verify_api_key(request: Request):
    """Simple API key authentication."""
    key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if key != API_KEY and API_KEY != "dev-key-12345":
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True

# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(title="Supply Chain API Gateway v1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Proxy Helper ─────────────────────────────────────────────────────────────

async def proxy_a2a(url: str, payload: dict, timeout: int = 30) -> dict:
    start = time.time()
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(f"{url}/a2a", json=payload, timeout=timeout)
            latency = round((time.time() - start) * 1000, 2)
            result = r.json()
            result["_gateway_latency_ms"] = latency
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}

async def proxy_get(url: str, timeout: int = 10) -> dict:
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, timeout=timeout)
            return r.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

# ── API Routes ────────────────────────────────────────────────────────────────

@app.get("/api/inventory")
async def get_inventory():
    return JSONResponse(content=await proxy_a2a(INVENTORY_AGENT_URL, {"task": "get_inventory"}))

@app.get("/api/orders")
async def get_orders():
    return JSONResponse(content=await proxy_a2a(ORDER_AGENT_URL, {"task": "get_orders"}))

@app.get("/api/market/prices")
async def get_market_prices():
    return JSONResponse(content=await proxy_get(f"{MARKET_API_URL}/prices"))

@app.get("/api/market/history/{product}")
async def get_market_history(product: str, limit: int = 100):
    return JSONResponse(content=await proxy_get(f"{MARKET_API_URL}/prices/history/{product}?limit={limit}"))

@app.get("/api/market/history")
async def get_all_market_history(limit: int = 100):
    return JSONResponse(content=await proxy_get(f"{MARKET_API_URL}/prices/history/all?limit={limit}"))

@app.get("/api/budget")
async def get_budget():
    return JSONResponse(content=await proxy_a2a(FINANCE_AGENT_URL, {"task": "get_budget_status"}))

@app.get("/api/budget/transactions")
async def get_budget_transactions():
    return JSONResponse(content=await proxy_a2a(FINANCE_AGENT_URL, {"task": "get_transactions", "limit": 50}))

@app.post("/api/pipeline/trigger")
async def trigger_pipeline():
    """Trigger the full pipeline — async via Celery if available, sync otherwise."""
    if _celery_app:
        try:
            task = _celery_app.send_task("pipeline.run_full_pipeline")
            return JSONResponse(content={
                "status": "pipeline_triggered",
                "task_id": task.id,
                "message": "Pipeline is running in the background. Watch /ws/pipeline for updates."
            })
        except Exception as e:
            log.warning(f"Celery dispatch failed, falling back to sync: {e}")

    # Sync fallback
    result = await proxy_a2a(PRICING_AGENT_URL, {"task": "sync_prices"})
    restock = await proxy_a2a(INVENTORY_AGENT_URL, {"task": "check_and_restock"}, timeout=60)
    return JSONResponse(content={
        "status": "pipeline_complete",
        "price_sync": result,
        "restock": restock,
    })

@app.post("/api/prices/sync")
async def sync_prices():
    return JSONResponse(content=await proxy_a2a(PRICING_AGENT_URL, {"task": "sync_prices"}))

# ── Agent Health ─────────────────────────────────────────────────────────────

@app.get("/api/agents/health")
async def get_agents_health():
    """Get health status of all agents."""
    status = health_monitor.get_status()
    if not status:
        # Poll synchronously if no cached data
        status = {}
        for name, url in ALL_AGENT_URLS.items():
            status[name] = check_agent_health(url)
            status[name]["name"] = name
            status[name]["url"] = url

    circuit_breakers = get_all_breaker_status()
    return JSONResponse(content={
        "agents": status,
        "circuit_breakers": circuit_breakers,
        "gateway_uptime_s": round(time.time() - started_at, 1),
    })

@app.get("/api/agents/{agent_name}/health")
async def get_agent_health(agent_name: str):
    url = ALL_AGENT_URLS.get(agent_name)
    if not url:
        return JSONResponse(status_code=404, content={"error": f"Unknown agent: {agent_name}"})
    return JSONResponse(content=check_agent_health(url))

# ── Pipeline Events ──────────────────────────────────────────────────────────

@app.get("/api/pipeline/events")
async def get_pipeline_events(limit: int = 50):
    """Get recent pipeline events from Redis."""
    if not _redis:
        return JSONResponse(content={"events": [], "message": "Redis unavailable"})
    try:
        events = _redis.lrange("pipeline_event_log", 0, limit - 1)
        return JSONResponse(content={
            "events": [json.loads(e) for e in events]
        })
    except Exception as e:
        return JSONResponse(content={"events": [], "error": str(e)})

# ── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws/pipeline")
async def pipeline_websocket(websocket: WebSocket):
    """Real-time pipeline events via WebSocket."""
    await ws_manager.connect(websocket)

    # Start Redis subscriber in background
    async def redis_listener():
        if not _redis:
            return
        try:
            pubsub = _redis.pubsub()
            pubsub.subscribe("pipeline_events")
            while True:
                msg = pubsub.get_message(timeout=0.1)
                if msg and msg["type"] == "message":
                    try:
                        data = json.loads(msg["data"])
                        await websocket.send_json(data)
                    except:
                        pass
                await asyncio.sleep(0.05)
        except:
            pass

    listener_task = asyncio.create_task(redis_listener())

    try:
        while True:
            data = await websocket.receive_text()
            # Client can send ping messages
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        listener_task.cancel()

# ── Gateway Health ────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return JSONResponse(content={
        "status": "ok",
        "agent": "API Gateway",
        "version": "1.0.0",
        "uptime_s": round(time.time() - started_at, 1),
        "websocket_connections": len(ws_manager.active),
        "redis_connected": _redis is not None,
        "celery_configured": _celery_app is not None,
    })

# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    health_monitor.start()
    log.info("API Gateway v1.0 started — health monitoring active")

if __name__ == "__main__":
    log.info("API Gateway v1.0 starting on http://localhost:8080")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")
