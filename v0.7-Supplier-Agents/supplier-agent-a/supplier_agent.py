"""
Supplier Agent — v0.7 Supplier Agents
Reusable template for all 3 suppliers.
Each supplier's personality comes from .env:
  - BASE_PRICE_MULTIPLIER  → how expensive they are
  - DELIVERY_DAYS          → how fast they deliver
  - RELIABILITY            → chance of accepting a bid (0.0–1.0)

Copy this file into each supplier folder and add the matching .env.
"""

import logging
import sys
import os
import random
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
log = logging.getLogger("supplier-agent")

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()

PORT                   = int(os.getenv("PORT",                   8011))
SUPPLIER_NAME          = os.getenv("SUPPLIER_NAME",              "SupplierA")
BASE_PRICE_MULTIPLIER  = float(os.getenv("BASE_PRICE_MULTIPLIER", 1.0))
DELIVERY_DAYS          = int(os.getenv("DELIVERY_DAYS",          3))
RELIABILITY            = float(os.getenv("RELIABILITY",          0.9))

# ── Agent Card ────────────────────────────────────────────────────────────────

AGENT_CARD = {
    "name":        SUPPLIER_NAME,
    "description": f"Supplier agent that responds to bid requests. Delivery: {DELIVERY_DAYS} days. Reliability: {int(RELIABILITY * 100)}%.",
    "version":     "0.7.0",
    "url":         f"http://localhost:{PORT}",
    "capabilities": ["submit_bid"],
    "skills": [
        {
            "name":        "submit_bid",
            "description": "Respond to a bid request with price and delivery time",
            "input_schema": {
                "type": "object",
                "properties": {
                    "product":        {"type": "string",  "description": "Product to supply"},
                    "quantity":       {"type": "integer", "description": "Quantity requested"},
                    "base_price":     {"type": "number",  "description": "Reference market price per unit"},
                    "deadline_days":  {"type": "integer", "description": "Maximum acceptable delivery days"}
                },
                "required": ["product", "quantity", "base_price"]
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "status":           {"type": "string"},
                    "supplier":         {"type": "string"},
                    "unit_price":       {"type": "number"},
                    "total_price":      {"type": "number"},
                    "delivery_days":    {"type": "integer"},
                    "reliability_pct":  {"type": "number"},
                    "score":            {"type": "number"}
                }
            }
        }
    ],
    "authentication": {
        "type":        "none",
        "description": "No auth required"
    },
    "supplier_profile": {
        "price_multiplier": BASE_PRICE_MULTIPLIER,
        "delivery_days":    DELIVERY_DAYS,
        "reliability":      RELIABILITY
    }
}

# ── Scoring ───────────────────────────────────────────────────────────────────

def calculate_score(unit_price: float, base_price: float, delivery_days: int, reliability: float) -> float:
    """
    Score combining price + delivery time + reliability.
    Lower is better.

    Formula:
      price_score    = unit_price / base_price        (1.0 = market price, lower is better)
      delivery_score = delivery_days / 7              (normalized to 7-day max)
      reliability_score = 1 - reliability             (lower reliability = higher penalty)

    Weighted: 50% price, 30% delivery, 20% reliability
    """
    price_score       = unit_price / base_price
    delivery_score    = delivery_days / 7
    reliability_score = 1 - reliability
    score = (0.5 * price_score) + (0.3 * delivery_score) + (0.2 * reliability_score)
    return round(score, 4)

# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(title=f"Supplier Agent — {SUPPLIER_NAME}")

@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)

@app.post("/a2a")
async def handle_a2a(request: Request):
    try:
        body         = await request.json()
        task         = body.get("task")
        product      = body.get("product")
        quantity     = body.get("quantity")
        base_price   = body.get("base_price")
        deadline_days = body.get("deadline_days", 99)

        log.info(f"Bid request: task={task} product={product} qty={quantity} base_price={base_price}")

        if task != "submit_bid":
            return JSONResponse(status_code=400, content={"status": "error", "message": f"Unknown task: {task}"})

        if not product or not quantity or not base_price:
            return JSONResponse(status_code=400, content={"status": "error", "message": "Missing product, quantity or base_price"})

        # Simulate reliability — occasionally decline bids
        if random.random() > RELIABILITY:
            log.info(f"Declining bid (reliability simulation)")
            return JSONResponse(content={
                "status":   "declined",
                "supplier": SUPPLIER_NAME,
                "reason":   "Capacity unavailable at this time"
            })

        # Calculate bid
        unit_price  = round(base_price * BASE_PRICE_MULTIPLIER, 2)
        total_price = round(unit_price * quantity, 2)
        score       = calculate_score(unit_price, base_price, DELIVERY_DAYS, RELIABILITY)

        # Check if we can meet the deadline
        if DELIVERY_DAYS > deadline_days:
            return JSONResponse(content={
                "status":   "declined",
                "supplier": SUPPLIER_NAME,
                "reason":   f"Cannot meet {deadline_days}-day deadline (we need {DELIVERY_DAYS} days)"
            })

        log.info(f"Submitting bid: unit_price={unit_price} delivery={DELIVERY_DAYS}d score={score}")

        return JSONResponse(content={
            "status":          "accepted",
            "supplier":        SUPPLIER_NAME,
            "product":         product,
            "quantity":        quantity,
            "unit_price":      unit_price,
            "total_price":     total_price,
            "delivery_days":   DELIVERY_DAYS,
            "reliability_pct": int(RELIABILITY * 100),
            "score":           score
        })

    except Exception as e:
        log.error(f"Error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/health")
async def health():
    return JSONResponse(content={
        "status":           "ok",
        "supplier":         SUPPLIER_NAME,
        "price_multiplier": BASE_PRICE_MULTIPLIER,
        "delivery_days":    DELIVERY_DAYS,
        "reliability":      RELIABILITY
    })

# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info(f"{SUPPLIER_NAME} starting on port {PORT}")
    log.info(f"Price multiplier: {BASE_PRICE_MULTIPLIER}x | Delivery: {DELIVERY_DAYS} days | Reliability: {int(RELIABILITY*100)}%")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")