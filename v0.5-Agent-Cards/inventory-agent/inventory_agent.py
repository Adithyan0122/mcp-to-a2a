"""
Inventory Agent — v0.5 Agent Cards
Runs on port 8000.
Checks stock levels, discovers Order + Notification agents via Agent Cards,
triggers restock orders and alerts autonomously.
"""

import logging
import sys
import os
import time
import psycopg2
import psycopg2.extras
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
import threading

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
log = logging.getLogger("inventory-agent")

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()

DB_CONFIG = {
    "dbname":   os.getenv("DB_NAME",     "supply_db"),
    "user":     os.getenv("DB_USER",     "adithyan"),
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "password": os.getenv("DB_PASSWORD", ""),
}

ORDER_AGENT_URL        = os.getenv("ORDER_AGENT_URL",        "http://localhost:8001")
NOTIFICATION_AGENT_URL = os.getenv("NOTIFICATION_AGENT_URL", "http://localhost:8002")
RESTOCK_THRESHOLD      = int(os.getenv("RESTOCK_THRESHOLD",  15))
RESTOCK_QUANTITY       = int(os.getenv("RESTOCK_QUANTITY",   20))

# ── Agent Card ────────────────────────────────────────────────────────────────

AGENT_CARD = {
    "name":        "Inventory Agent",
    "description": "Monitors stock levels and triggers restock workflows",
    "version":     "0.5.0",
    "url":         "http://localhost:8000",
    "capabilities": ["check_stock", "trigger_restock"],
    "skills": [
        {
            "name":        "check_stock",
            "description": "Check current stock levels for all products",
            "input_schema": {
                "type":       "object",
                "properties": {}
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "products":   {"type": "array"},
                    "low_stock":  {"type": "array"},
                    "total":      {"type": "integer"}
                }
            }
        },
        {
            "name":        "trigger_restock",
            "description": "Manually trigger a restock check and order flow",
            "input_schema": {
                "type":       "object",
                "properties": {
                    "product": {
                        "type":        "string",
                        "description": "Specific product to restock (optional — restocks all low stock if omitted)"
                    }
                }
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "restocked": {"type": "array"},
                    "status":    {"type": "string"}
                }
            }
        }
    ],
    "authentication": {
        "type":        "none",
        "description": "No auth required for internal agent communication"
    },
    "contact": "supply-chain-system"
}

# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(**DB_CONFIG)

def init_db():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id        SERIAL PRIMARY KEY,
            product   TEXT           NOT NULL UNIQUE,
            quantity  INTEGER        DEFAULT 0,
            price     NUMERIC(10, 2) DEFAULT 0.00
        )
    """)
    cur.execute("SELECT COUNT(*) FROM inventory")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO inventory (product, quantity, price) VALUES (%s, %s, %s)",
            [
                ("Laptop",   10, 999.99),
                ("Mouse",    50,  29.99),
                ("Keyboard", 30,  79.99),
                ("Monitor",   8, 349.99),
                ("Webcam",   20,  89.99),
            ]
        )
        log.info("Inventory seeded with 5 products")
    conn.commit()
    cur.close()
    conn.close()
    log.info("Inventory table initialized in supply_db")

def get_all_products() -> list:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM inventory ORDER BY quantity ASC")
    products = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return products

def get_low_stock() -> list:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT * FROM inventory WHERE quantity < %s ORDER BY quantity ASC",
        (RESTOCK_THRESHOLD,)
    )
    products = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return products

# ── A2A Discovery ─────────────────────────────────────────────────────────────

# Cache discovered agent cards so we don't re-fetch every time
_agent_card_cache = {}

def discover_agent(url: str) -> tuple[dict | None, float]:
    if url in _agent_card_cache:
        log.info(f"Agent Card cache hit: {url}")
        return _agent_card_cache[url], 0.0

    try:
        start    = time.time()
        response = httpx.get(f"{url}/.well-known/agent.json", timeout=5)
        latency  = round((time.time() - start) * 1000, 2)
        card     = response.json()
        _agent_card_cache[url] = card
        log.info(f"Discovered agent: {card.get('name')} — capabilities: {card.get('capabilities')} ({latency}ms)")
        return card, latency
    except Exception as e:
        log.error(f"Failed to discover agent at {url}: {e}")
        return None, 0.0

def send_a2a(url: str, payload: dict) -> tuple[dict, float]:
    try:
        start    = time.time()
        response = httpx.post(f"{url}/a2a", json=payload, timeout=5)
        latency  = round((time.time() - start) * 1000, 2)
        return response.json(), latency
    except Exception as e:
        log.error(f"A2A request failed to {url}: {e}")
        return {"status": "error", "message": str(e)}, 0.0

# ── Core Restock Logic ────────────────────────────────────────────────────────

def run_restock(specific_product: str = None) -> dict:
    log.info("=" * 60)
    log.info("Starting restock check")

    # Step 1 — Discover agents
    log.info("── Discovering agents ──────────────────────────────────")
    order_card, order_discovery_ms        = discover_agent(ORDER_AGENT_URL)
    notif_card, notif_discovery_ms        = discover_agent(NOTIFICATION_AGENT_URL)

    if not order_card:
        return {"status": "error", "message": "Could not reach Order Agent"}

    # Step 2 — Check inventory
    if specific_product:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM inventory WHERE LOWER(product) = LOWER(%s)", (specific_product,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        low_stock = [dict(row)] if row else []
    else:
        low_stock = get_low_stock()

    log.info(f"── Inventory check ─────────────────────────────────────")
    all_products = get_all_products()
    for p in all_products:
        flag = " ⚠️  LOW" if p["quantity"] < RESTOCK_THRESHOLD else ""
        log.info(f"  {p['product']:12} qty={p['quantity']:3}{flag}")

    if not low_stock:
        log.info("All products above threshold — no restock needed")
        return {"status": "ok", "message": "No restock needed", "restocked": []}

    log.info(f"{len(low_stock)} product(s) need restocking")

    # Step 3 — Send low stock alerts
    log.info("── Sending low stock alerts ────────────────────────────")
    for product in low_stock:
        if notif_card:
            result, ms = send_a2a(NOTIFICATION_AGENT_URL, {
                "task":       "send_alert",
                "event_type": "low_stock",
                "product":    product["product"],
                "details": {
                    "quantity":  product["quantity"],
                    "threshold": RESTOCK_THRESHOLD
                }
            })
            log.info(f"  Low stock alert for {product['product']}: {result.get('status')} ({ms}ms)")

    # Step 4 — Place restock orders
    log.info("── Placing restock orders ──────────────────────────────")
    restocked = []
    for product in low_stock:
        result, ms = send_a2a(ORDER_AGENT_URL, {
            "task":     "place_order",
            "product":  product["product"],
            "quantity": RESTOCK_QUANTITY
        })
        status = result.get("status")
        log.info(f"  Order for {product['product']}: {status} ({ms}ms)")
        if status == "success":
            restocked.append({
                "product":  product["product"],
                "quantity": RESTOCK_QUANTITY,
                "order_id": result.get("order", {}).get("id")
            })

    log.info(f"✅ Restock complete — {len(restocked)} order(s) placed")
    log.info("=" * 60)

    return {
        "status":    "success",
        "restocked": restocked
    }

# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(title="Inventory Agent")

@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)

@app.post("/a2a")
async def handle_a2a(request: Request):
    try:
        body = await request.json()
        task = body.get("task")

        if task == "check_stock":
            products  = get_all_products()
            low_stock = get_low_stock()
            return JSONResponse(content={
                "status":    "success",
                "products":  [dict(p, price=str(p["price"])) for p in products],
                "low_stock": [dict(p, price=str(p["price"])) for p in low_stock],
                "total":     len(products)
            })

        elif task == "trigger_restock":
            product = body.get("product")
            result  = run_restock(specific_product=product)
            return JSONResponse(content=result)

        else:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": f"Unknown task: {task}"}
            )

    except Exception as e:
        log.error(f"Error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/health")
async def health():
    return JSONResponse(content={
        "status":             "ok",
        "order_agent":        ORDER_AGENT_URL,
        "notification_agent": NOTIFICATION_AGENT_URL,
        "threshold":          RESTOCK_THRESHOLD
    })

# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    # Run initial restock check in background so server starts immediately
    threading.Thread(target=run_restock, daemon=True).start()
    log.info("Inventory Agent starting on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")