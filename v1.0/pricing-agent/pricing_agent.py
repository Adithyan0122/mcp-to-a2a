"""
Pricing Agent — v1.0
Runs on port 9001.
LLM-powered reprice decisions + memory logging + circuit breakers + tracing.
"""

import logging
import sys
import os
import time
import threading
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

# Ensure shared is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.config import (
    MARKET_API_URL, INVENTORY_AGENT_URL, DB_CONFIG, RESTOCK_THRESHOLD
)
from shared import llm
from shared.memory import MemoryClient
from shared.tracing import traced_a2a_call, traced_http_get
from shared.circuit_breaker import get_breaker
from shared.health import build_health_response, check_db_connection

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("pricing-agent")

load_dotenv()
PORT = int(os.getenv("PORT", 9001))

import psycopg2
import psycopg2.extras

memory = MemoryClient()
market_cb = get_breaker("pricing->market-api", failure_threshold=3, timeout=30)
inventory_cb = get_breaker("pricing->inventory-agent", failure_threshold=3, timeout=30)

AGENT_CARD = {
    "name": "Pricing Agent", "version": "1.0.0",
    "url": f"http://localhost:{PORT}",
    "capabilities": ["sync_prices"],
    "skills": [{
        "name": "sync_prices",
        "description": "Sync inventory prices with current market prices using LLM decisions",
        "input_schema": {"type": "object", "properties": {}}
    }]
}

started_at = time.time()


def get_db_prices() -> dict:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT product, price FROM inventory")
    rows = {r["product"]: float(r["price"]) for r in cur.fetchall()}
    cur.close()
    conn.close()
    return rows


def sync_prices() -> dict:
    """Fetch market prices, use LLM to decide repricing, update via Inventory Agent."""
    try:
        # Get market prices through circuit breaker
        market_data, _ = market_cb.call(traced_http_get, f"{MARKET_API_URL}/prices")
        if "error" in market_data:
            return {"status": "error", "message": market_data.get("message", "Market API unreachable")}

        market = market_data["prices"]
        db_prices = get_db_prices()
        updates = []

        for product, market_price in market.items():
            db_price = db_prices.get(product, market_price)
            if db_price == 0:
                db_price = market_price
            drift_pct = ((market_price - db_price) / db_price) * 100

            # Get price history for LLM context
            price_history = memory.get_price_history(product, days=7)

            # LLM decides whether to reprice
            reprice_ctx = {
                "product": product,
                "db_price": db_price,
                "market_price": market_price,
                "drift_pct": drift_pct,
                "volatility": "moderate",
                "price_history": price_history[:5],
            }
            decision = llm.decide_reprice(reprice_ctx)

            # Record the LLM decision in memory
            memory.record_decision("pricing-agent", {
                "type": "reprice_decision",
                "product": product,
                "decision": decision,
                "context": {"db_price": db_price, "market_price": market_price, "drift_pct": drift_pct},
            })

            if decision.get("should_reprice", False):
                new_price = decision.get("suggested_price", market_price)
                pct = ((new_price - db_price) / db_price) * 100

                try:
                    inventory_cb.call(
                        traced_a2a_call,
                        INVENTORY_AGENT_URL,
                        {
                            "task": "update_price",
                            "product": product,
                            "new_price": new_price,
                            "old_price": db_price,
                            "pct_change": round(pct, 2),
                        },
                    )
                    updates.append({
                        "product": product,
                        "old": db_price,
                        "new": new_price,
                        "pct": round(pct, 2),
                        "reasoning": decision.get("reasoning", ""),
                    })

                    # Record price event in memory
                    memory.record_price_event(product, db_price, new_price, round(pct, 2), "market_sync")
                    log.info(f"Repriced {product}: ${db_price} → ${new_price} ({pct:+.1f}%) — {decision.get('reasoning', '')[:60]}")

                except Exception as e:
                    log.warning(f"Failed to update {product}: {e}")

        log.info(f"Price sync complete — {len(updates)} update(s)")
        return {"status": "success", "updates": updates, "tick": market_data.get("tick")}

    except Exception as e:
        log.error(f"Price sync failed: {e}")
        return {"status": "error", "message": str(e)}


def background_sync():
    """Sync prices every 10 seconds in the background."""
    while True:
        time.sleep(10)
        try:
            sync_prices()
        except Exception as e:
            log.warning(f"Background sync error: {e}")


app = FastAPI(title="Pricing Agent v1.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"])

@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)

@app.post("/a2a")
async def handle_a2a(request: Request):
    try:
        body = await request.json()
        task = body.get("task")
        if task == "sync_prices":
            result = sync_prices()
            return JSONResponse(content=result)
        else:
            return JSONResponse(status_code=400,
                content={"status": "error", "message": f"Unknown task: {task}"})
    except Exception as e:
        return JSONResponse(status_code=500,
            content={"status": "error", "message": str(e)})

@app.get("/health")
async def health():
    db_ok = check_db_connection(DB_CONFIG)
    deps = {
        "market-api": market_cb.get_status(),
        "inventory-agent": inventory_cb.get_status(),
    }
    return JSONResponse(content=build_health_response(
        "Pricing Agent", "1.0.0", db_connected=db_ok,
        dependencies=deps, extra={"market_url": MARKET_API_URL}
    ))

if __name__ == "__main__":
    threading.Thread(target=background_sync, daemon=True).start()
    log.info(f"Pricing Agent v1.0 starting on http://localhost:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
