"""
Market API — v0.8 Pricing Agent
Runs on port 9000.
Simulates a live market price feed using random walk.
Prices drift realistically over time — up or down each tick.

Random walk formula:
  new_price = old_price * (1 + drift + volatility * random_normal())
"""

import logging
import sys
import os
import time
import random
import math
import threading
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
log = logging.getLogger("market-api")

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()

PORT          = int(os.getenv("PORT",          9000))
VOLATILITY    = float(os.getenv("VOLATILITY",  0.02))
DRIFT         = float(os.getenv("DRIFT",       0.001))
TICK_INTERVAL = int(os.getenv("TICK_INTERVAL", 1))

# ── Market State ──────────────────────────────────────────────────────────────

# Base prices — what the market starts at
BASE_PRICES = {
    "Laptop":   999.99,
    "Mouse":     29.99,
    "Keyboard":  79.99,
    "Monitor":  349.99,
    "Webcam":    89.99,
}

# Live prices — updated every tick
market_prices = {k: v for k, v in BASE_PRICES.items()}

# Price history — last 100 ticks per product
price_history = {k: [v] for k, v in BASE_PRICES.items()}

# Tick counter
tick_count = 0
started_at = time.time()

# Lock for thread safety
lock = threading.Lock()

# ── Random Walk ───────────────────────────────────────────────────────────────

def tick():
    """Advance market prices by one tick using random walk."""
    global tick_count
    with lock:
        for product in market_prices:
            old_price  = market_prices[product]
            shock      = random.gauss(0, 1)
            pct_change = DRIFT + VOLATILITY * shock
            new_price  = round(old_price * (1 + pct_change), 2)

            # Floor at 10% of base price — prices can't go to zero
            floor = BASE_PRICES[product] * 0.10
            new_price = max(new_price, floor)

            market_prices[product] = new_price

            # Keep last 100 ticks of history
            price_history[product].append(new_price)
            if len(price_history[product]) > 100:
                price_history[product].pop(0)

        tick_count += 1

def market_loop():
    """Background thread — ticks the market every TICK_INTERVAL seconds."""
    log.info(f"Market ticking every {TICK_INTERVAL}s | volatility={VOLATILITY} drift={DRIFT}")
    while True:
        time.sleep(TICK_INTERVAL)
        tick()

# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(title="Market API")

@app.get("/prices")
async def get_prices():
    """Current market prices for all products."""
    with lock:
        return JSONResponse(content={
            "tick":      tick_count,
            "uptime_s":  round(time.time() - started_at, 1),
            "prices":    dict(market_prices),
            "base":      BASE_PRICES
        })

@app.get("/prices/{product}")
async def get_price(product: str):
    """Current market price for one product."""
    with lock:
        # Case-insensitive lookup
        match = next((k for k in market_prices if k.lower() == product.lower()), None)
        if not match:
            return JSONResponse(status_code=404, content={"error": f"Product '{product}' not found"})

        current   = market_prices[match]
        base      = BASE_PRICES[match]
        pct_drift = round(((current - base) / base) * 100, 2)

        return JSONResponse(content={
            "product":   match,
            "price":     current,
            "base":      base,
            "pct_drift": pct_drift,
            "tick":      tick_count
        })

@app.get("/history/{product}")
async def get_history(product: str):
    """Price history for one product (last 100 ticks)."""
    with lock:
        match = next((k for k in price_history if k.lower() == product.lower()), None)
        if not match:
            return JSONResponse(status_code=404, content={"error": f"Product '{product}' not found"})

        history = price_history[match]
        return JSONResponse(content={
            "product": match,
            "history": history,
            "ticks":   len(history),
            "min":     min(history),
            "max":     max(history),
            "current": history[-1]
        })

@app.get("/health")
async def health():
    return JSONResponse(content={
        "status":     "ok",
        "tick":       tick_count,
        "uptime_s":   round(time.time() - started_at, 1),
        "volatility": VOLATILITY,
        "drift":      DRIFT
    })

# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Start market tick loop in background
    t = threading.Thread(target=market_loop, daemon=True)
    t.start()
    log.info(f"Market API starting on http://localhost:{PORT}")
    log.info(f"Volatility: {VOLATILITY} | Drift: {DRIFT} | Tick: {TICK_INTERVAL}s")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")