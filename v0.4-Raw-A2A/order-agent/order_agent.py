"""
Order Agent — v0.4 Raw A2A
Runs as an HTTP server on port 8001.
Receives restock requests from the Inventory Agent via A2A protocol.
"""

import json
import logging
import sys
import os
import psycopg2
import psycopg2.extras
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
    "dbname":   os.getenv("DB_NAME",     "orders_db"),
    "user":     os.getenv("DB_USER",     "adithyan"),
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "password": os.getenv("DB_PASSWORD", ""),
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
            status     TEXT    DEFAULT 'pending',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    log.info("Orders DB initialized")

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

# ── Agent Card ────────────────────────────────────────────────────────────────
# The Agent Card is how agents discover and describe themselves in A2A.
# It's served at /.well-known/agent.json

AGENT_CARD = {
    "name": "Order Agent",
    "description": "Receives restock requests and creates orders in the orders database",
    "version": "0.4.0",
    "url": "http://localhost:8001",
    "capabilities": ["place_order"],
    "contact": "inventory-system"
}

# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(title="Order Agent")

@app.get("/.well-known/agent.json")
async def agent_card():
    """A2A Agent Card — how other agents discover this agent."""
    return JSONResponse(content=AGENT_CARD)

@app.post("/a2a")
async def handle_a2a(request: Request):
    """
    A2A endpoint — receives task requests from other agents.
    Expects JSON: { "task": "place_order", "product": "...", "quantity": ... }
    """
    try:
        body = await request.json()
        log.info(f"Received A2A request: {body}")

        task     = body.get("task")
        product  = body.get("product")
        quantity = body.get("quantity")

        if task != "place_order":
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": f"Unknown task: {task}"}
            )

        if not product or not quantity:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Missing product or quantity"}
            )

        if quantity <= 0:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Quantity must be positive"}
            )

        # Create the order in DB
        order = create_order(product, quantity)
        log.info(f"Order placed: {order}")

        return JSONResponse(content={
            "status": "success",
            "message": f"Order placed for {quantity}x {product}",
            "order": {
                "id":       order["id"],
                "product":  order["product"],
                "quantity": order["quantity"],
                "status":   order["status"],
                "created_at": str(order["created_at"])
            }
        })

    except Exception as e:
        log.error(f"Error handling A2A request: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )

@app.get("/orders")
async def list_orders():
    """View all orders — useful for verifying the agent worked."""
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM orders ORDER BY created_at DESC")
    orders = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return JSONResponse(content={"orders": [
        {**o, "created_at": str(o["created_at"])} for o in orders
    ]})

# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    log.info("Order Agent starting on http://localhost:8001")
    log.info("Agent Card: http://localhost:8001/.well-known/agent.json")
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning")