"""
Order Agent — v0.5 Agent Cards
Runs on port 8001.
Receives restock requests, creates orders in supply_db,
then notifies the Notification Agent via A2A.
Exposes a proper Agent Card with full skill schema.
"""

import json
import logging
import sys
import os
import psycopg2
import psycopg2.extras
import httpx
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
log = logging.getLogger("order-agent")

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()

DB_CONFIG = {
    "dbname":   os.getenv("DB_NAME",     "supply_db"),
    "user":     os.getenv("DB_USER",     "adithyan"),
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "password": os.getenv("DB_PASSWORD", ""),
}

NOTIFICATION_AGENT_URL = os.getenv("NOTIFICATION_AGENT_URL", "http://localhost:8002")

# ── Agent Card ────────────────────────────────────────────────────────────────

AGENT_CARD = {
    "name":        "Order Agent",
    "description": "Places and tracks restock orders for inventory products",
    "version":     "0.5.0",
    "url":         "http://localhost:8001",
    "capabilities": ["place_order", "get_orders"],
    "skills": [
        {
            "name":        "place_order",
            "description": "Create a new restock order for a product",
            "input_schema": {
                "type": "object",
                "properties": {
                    "product":  {"type": "string",  "description": "Product name to restock"},
                    "quantity": {"type": "integer", "description": "Quantity to order"}
                },
                "required": ["product", "quantity"]
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "status":  {"type": "string"},
                    "order":   {"type": "object"},
                    "message": {"type": "string"}
                }
            }
        },
        {
            "name":        "get_orders",
            "description": "Retrieve all placed orders",
            "input_schema": {
                "type":       "object",
                "properties": {}
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "orders": {"type": "array"}
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
        CREATE TABLE IF NOT EXISTS orders (
            id         SERIAL PRIMARY KEY,
            product    TEXT    NOT NULL,
            quantity   INTEGER NOT NULL,
            status     TEXT    DEFAULT 'placed',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    log.info("Orders table initialized in supply_db")

def create_order(product: str, quantity: int) -> dict:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "INSERT INTO orders (product, quantity, status) VALUES (%s, %s, 'placed') RETURNING *",
        (product, quantity)
    )
    order = dict(cur.fetchone())
    conn.commit()
    cur.close()
    conn.close()
    return order

def fetch_all_orders() -> list:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM orders ORDER BY created_at DESC")
    orders = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return orders

# ── Notify Helper ─────────────────────────────────────────────────────────────

def notify(event_type: str, product: str, details: dict):
    try:
        httpx.post(
            f"{NOTIFICATION_AGENT_URL}/a2a",
            json={
                "task":       "send_alert",
                "event_type": event_type,
                "product":    product,
                "details":    details
            },
            timeout=5
        )
        log.info(f"Notification sent: {event_type} for {product}")
    except Exception as e:
        log.warning(f"Failed to notify: {e} — continuing anyway")

# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(title="Order Agent")

@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)

@app.post("/a2a")
async def handle_a2a(request: Request):
    try:
        body     = await request.json()
        task     = body.get("task")
        product  = body.get("product")
        quantity = body.get("quantity")

        log.info(f"Received A2A: task={task} product={product} quantity={quantity}")

        if task == "place_order":
            if not product:
                return JSONResponse(status_code=400, content={"status": "error", "message": "Missing product"})
            if not quantity or quantity <= 0:
                return JSONResponse(status_code=400, content={"status": "error", "message": "Quantity must be positive"})

            order = create_order(product, quantity)
            log.info(f"Order created: id={order['id']} product={product} qty={quantity}")

            # Notify the Notification Agent
            notify("order_placed", product, {
                "order_id": order["id"],
                "quantity": quantity
            })

            return JSONResponse(content={
                "status":  "success",
                "message": f"Order placed for {quantity}x {product}",
                "order": {
                    "id":         order["id"],
                    "product":    order["product"],
                    "quantity":   order["quantity"],
                    "status":     order["status"],
                    "created_at": str(order["created_at"])
                }
            })

        elif task == "get_orders":
            orders = fetch_all_orders()
            return JSONResponse(content={
                "status": "success",
                "orders": [{**o, "created_at": str(o["created_at"])} for o in orders]
            })

        else:
            return JSONResponse(status_code=400, content={"status": "error", "message": f"Unknown task: {task}"})

    except Exception as e:
        log.error(f"Error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/health")
async def health():
    return JSONResponse(content={"status": "ok", "notification_agent": NOTIFICATION_AGENT_URL})

# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    log.info("Order Agent starting on http://localhost:8001")
    log.info(f"Will notify: {NOTIFICATION_AGENT_URL}")
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning")