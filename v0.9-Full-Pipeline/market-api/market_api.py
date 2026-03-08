"""
Market API — v0.9 Full Pipeline
Runs on port 9000.
Random walk price feed. Identical to v0.8.
"""

import logging
import sys
import os
import time
import random
import threading
from dotenv import load_dotenv
from fastapi import FastAPI
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
price_history = {k: [v] for k, v in BASE_PRICES.items()}
tick_count = 0
started_at = time.time()
lock = threading.Lock()

def tick():
    global tick_count
    with lock:
        for product in market_prices:
            old_price  = market_prices[product]
            shock      = random.gauss(0, 1)
            pct_change = DRIFT + VOLATILITY * shock
            new_price  = round(max(old_price * (1 + pct_change), BASE_PRICES[product] * 0.10), 2)
            market_prices[product] = new_price
            price_history[product].append(new_price)
            if len(price_history[product]) > 100:
                price_history[product].pop(0)
        tick_count += 1

def market_loop():
    while True:
        time.sleep(TICK_INTERVAL)
        tick()

app = FastAPI(title="Market API")

@app.get("/prices")
async def get_prices():
    with lock:
        return JSONResponse(content={"tick": tick_count, "uptime_s": round(time.time() - started_at, 1),
            "prices": dict(market_prices), "base": BASE_PRICES})

@app.get("/prices/{product}")
async def get_price(product: str):
    with lock:
        match = next((k for k in market_prices if k.lower() == product.lower()), None)
        if not match:
            return JSONResponse(status_code=404, content={"error": f"Product '{product}' not found"})
        current = market_prices[match]
        base    = BASE_PRICES[match]
        return JSONResponse(content={"product": match, "price": current, "base": base,
            "pct_drift": round(((current - base) / base) * 100, 2), "tick": tick_count})

@app.get("/health")
async def health():
    return JSONResponse(content={"status": "ok", "tick": tick_count, "uptime_s": round(time.time() - started_at, 1)})

if __name__ == "__main__":
    threading.Thread(target=market_loop, daemon=True).start()
    log.info(f"Market API starting on http://localhost:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")