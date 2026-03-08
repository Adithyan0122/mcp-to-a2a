"""
Market API — v1.0
Runs on port 9000.
Random walk price feed with history endpoint for frontend charts.
"""

import logging
import sys
import os
import time
import random
import threading
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("market-api")

load_dotenv()
PORT          = int(os.getenv("PORT",          9000))
VOLATILITY    = float(os.getenv("VOLATILITY",  0.02))
DRIFT         = float(os.getenv("DRIFT",       0.001))
TICK_INTERVAL = int(os.getenv("TICK_INTERVAL", 1))

BASE_PRICES = {"Laptop": 999.99, "Mouse": 29.99, "Keyboard": 79.99, "Monitor": 349.99, "Webcam": 89.99}
market_prices = {k: v for k, v in BASE_PRICES.items()}
price_history = {k: [{"price": v, "tick": 0, "timestamp": time.time()}] for k, v in BASE_PRICES.items()}
tick_count = 0
started_at = time.time()
lock = threading.Lock()

def tick():
    global tick_count
    with lock:
        now = time.time()
        for product in market_prices:
            old_price  = market_prices[product]
            shock      = random.gauss(0, 1)
            pct_change = DRIFT + VOLATILITY * shock
            new_price  = round(max(old_price * (1 + pct_change), BASE_PRICES[product] * 0.10), 2)
            market_prices[product] = new_price
            price_history[product].append({
                "price": new_price, "tick": tick_count + 1, "timestamp": now
            })
            if len(price_history[product]) > 200:
                price_history[product].pop(0)
        tick_count += 1

def market_loop():
    while True:
        time.sleep(TICK_INTERVAL)
        tick()

app = FastAPI(title="Market API v1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

AGENT_CARD = {
    "name": "Market API", "version": "1.0.0",
    "url": f"http://localhost:{PORT}",
    "capabilities": ["get_prices", "get_price_history"],
    "skills": [
        {"name": "get_prices", "description": "Get current market prices for all products"},
        {"name": "get_price_history", "description": "Get price history for charting"}
    ]
}

@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)

@app.get("/prices")
async def get_prices():
    with lock:
        return JSONResponse(content={
            "tick": tick_count,
            "uptime_s": round(time.time() - started_at, 1),
            "prices": dict(market_prices),
            "base": BASE_PRICES
        })

@app.get("/prices/{product}")
async def get_price(product: str):
    with lock:
        match = next((k for k in market_prices if k.lower() == product.lower()), None)
        if not match:
            return JSONResponse(status_code=404, content={"error": f"Product '{product}' not found"})
        current = market_prices[match]
        base    = BASE_PRICES[match]
        return JSONResponse(content={
            "product": match, "price": current, "base": base,
            "pct_drift": round(((current - base) / base) * 100, 2), "tick": tick_count
        })

@app.get("/prices/history/{product}")
async def get_price_history(product: str, limit: int = 100):
    """Get price history for a product — used by frontend charts."""
    with lock:
        match = next((k for k in price_history if k.lower() == product.lower()), None)
        if not match:
            return JSONResponse(status_code=404, content={"error": f"Product '{product}' not found"})
        history = price_history[match][-limit:]
        return JSONResponse(content={
            "product": match,
            "history": history,
            "current": market_prices[match],
            "base": BASE_PRICES[match],
            "ticks": len(history)
        })

@app.get("/prices/history/all")
async def get_all_history(limit: int = 100):
    """Get price history for all products."""
    with lock:
        result = {}
        for product in price_history:
            result[product] = {
                "history": price_history[product][-limit:],
                "current": market_prices[product],
                "base": BASE_PRICES[product],
            }
        return JSONResponse(content={"products": result, "tick": tick_count})

@app.get("/health")
async def health():
    return JSONResponse(content={
        "status": "ok",
        "agent": "Market API",
        "version": "1.0.0",
        "tick": tick_count,
        "uptime_s": round(time.time() - started_at, 1),
        "products": len(market_prices),
    })

if __name__ == "__main__":
    threading.Thread(target=market_loop, daemon=True).start()
    log.info(f"Market API v1.0 starting on http://localhost:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
