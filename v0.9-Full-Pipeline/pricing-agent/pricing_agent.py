"""
Pricing Agent — v0.9 Full Pipeline
Runs on port 9001.
Exposes an A2A endpoint so the MCP server can trigger a price sync on demand.
Also runs a background sync every 10 seconds.
"""

import logging
import sys
import os
import time
import threading
import psycopg2
import psycopg2.extras
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("pricing-agent")

load_dotenv()
PORT                   = int(os.getenv("PORT",                   9001))
MARKET_API_URL         = os.getenv("MARKET_API_URL",         "http://localhost:9000")
INVENTORY_AGENT_URL    = os.getenv("INVENTORY_AGENT_URL",    "http://localhost:8000")
REPRICE_THRESHOLD      = float(os.getenv("REPRICE_THRESHOLD", 0.05))
DB_CONFIG = {
    "dbname":   os.getenv("DB_NAME",     "pipeline_v9_db"),
    "user":     os.getenv("DB_USER",     "adithyan"),
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "password": os.getenv("DB_PASSWORD", ""),
}

AGENT_CARD = {
    "name": "Pricing Agent", "version": "0.9.0",
    "url": f"http://localhost:{PORT}", "capabilities": ["sync_prices"],
    "skills": [{"name": "sync_prices",
        "description": "Sync inventory prices with current market prices",
        "input_schema": {"type": "object", "properties": {}}}]
}

def get_db_prices() -> dict:
    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT product, price FROM inventory")
    rows = {r["product"]: float(r["price"]) for r in cur.fetchall()}
    cur.close()
    conn.close()
    return rows

def sync_prices() -> dict:
    """Fetch market prices, compare to DB, update anything drifted beyond threshold."""
    try:
        r           = httpx.get(f"{MARKET_API_URL}/prices", timeout=5)
        market_data = r.json()
        market      = market_data["prices"]
        db_prices   = get_db_prices()
        updates     = []

        for product, market_price in market.items():
            db_price = db_prices.get(product, market_price)
            drift    = abs((market_price - db_price) / db_price)

            if drift >= REPRICE_THRESHOLD:
                pct = ((market_price - db_price) / db_price) * 100
                try:
                    httpx.post(f"{INVENTORY_AGENT_URL}/a2a", json={
                        "task": "update_price", "product": product,
                        "new_price": market_price, "old_price": db_price,
                        "pct_change": round(pct, 2)
                    }, timeout=5)
                    updates.append({"product": product, "old": db_price,
                        "new": market_price, "pct": round(pct, 2)})
                    log.info(f"Repriced {product}: ${db_price} → ${market_price} ({pct:+.1f}%)")
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
        sync_prices()

app = FastAPI(title="Pricing Agent")

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
            return JSONResponse(status_code=400, content={"status": "error", "message": f"Unknown task: {task}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/health")
async def health():
    return JSONResponse(content={"status": "ok", "market": MARKET_API_URL})

if __name__ == "__main__":
    threading.Thread(target=background_sync, daemon=True).start()
    log.info(f"Pricing Agent starting on http://localhost:{PORT}")
    log.info(f"Background sync every 10s | threshold={REPRICE_THRESHOLD*100:.0f}%")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")