"""
Supplier Agent — v0.9 Full Pipeline
Reusable template for all 3 suppliers. Reads personality from .env.
Copy into supplier-agent-a/, supplier-agent-b/, supplier-agent-c/.
"""

import logging
import sys
import os
import random
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("supplier-agent")

load_dotenv()
PORT                  = int(os.getenv("PORT",                   8011))
SUPPLIER_NAME         = os.getenv("SUPPLIER_NAME",              "SupplierA")
BASE_PRICE_MULTIPLIER = float(os.getenv("BASE_PRICE_MULTIPLIER", 1.0))
DELIVERY_DAYS         = int(os.getenv("DELIVERY_DAYS",          3))
RELIABILITY           = float(os.getenv("RELIABILITY",          0.9))

AGENT_CARD = {
    "name": SUPPLIER_NAME, "version": "0.9.0",
    "url": f"http://localhost:{PORT}", "capabilities": ["submit_bid"],
    "skills": [{"name": "submit_bid", "input_schema": {"type": "object",
        "properties": {"product": {"type": "string"}, "quantity": {"type": "integer"},
        "base_price": {"type": "number"}, "deadline_days": {"type": "integer"}},
        "required": ["product", "quantity", "base_price"]}}],
    "supplier_profile": {"price_multiplier": BASE_PRICE_MULTIPLIER,
        "delivery_days": DELIVERY_DAYS, "reliability": RELIABILITY}
}

def calculate_score(unit_price, base_price, delivery_days, reliability):
    return round((0.5 * unit_price/base_price) + (0.3 * delivery_days/7) + (0.2 * (1-reliability)), 4)

app = FastAPI(title=f"Supplier — {SUPPLIER_NAME}")

@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)

@app.post("/a2a")
async def handle_a2a(request: Request):
    try:
        body          = await request.json()
        task          = body.get("task")
        product       = body.get("product")
        quantity      = body.get("quantity")
        base_price    = body.get("base_price")
        deadline_days = body.get("deadline_days", 99)

        if task != "submit_bid" or not product or not quantity or not base_price:
            return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid request"})

        if random.random() > RELIABILITY:
            return JSONResponse(content={"status": "declined", "supplier": SUPPLIER_NAME, "reason": "Capacity unavailable"})

        if DELIVERY_DAYS > deadline_days:
            return JSONResponse(content={"status": "declined", "supplier": SUPPLIER_NAME,
                "reason": f"Cannot meet {deadline_days}-day deadline (we need {DELIVERY_DAYS} days)"})

        unit_price  = round(base_price * BASE_PRICE_MULTIPLIER, 2)
        total_price = round(unit_price * quantity, 2)
        score       = calculate_score(unit_price, base_price, DELIVERY_DAYS, RELIABILITY)

        log.info(f"Bid: {product} qty={quantity} unit=${unit_price} score={score}")
        return JSONResponse(content={"status": "accepted", "supplier": SUPPLIER_NAME,
            "product": product, "quantity": quantity, "unit_price": unit_price,
            "total_price": total_price, "delivery_days": DELIVERY_DAYS,
            "reliability_pct": int(RELIABILITY * 100), "score": score})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/health")
async def health():
    return JSONResponse(content={"status": "ok", "supplier": SUPPLIER_NAME})

if __name__ == "__main__":
    log.info(f"{SUPPLIER_NAME} starting on port {PORT} | {BASE_PRICE_MULTIPLIER}x price | {DELIVERY_DAYS}d delivery | {int(RELIABILITY*100)}% reliable")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")