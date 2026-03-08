"""
Order Agent — v0.7 Supplier Agents
Runs on port 8001.
Receives the winning supplier bid and creates a confirmed order in supplier_db.
"""

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
    "dbname":   os.getenv("DB_NAME",     "supplier_db"),
    "user":     os.getenv("DB_USER",     "adithyan"),
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "password": os.getenv("DB_PASSWORD", ""),
}

# ── Agent Card ────────────────────────────────────────────────────────────────

AGENT_CARD = {
    "name":        "Order Agent",
    "description": "Confirms and records orders with the winning supplier",
    "version":     "0.7.0",
    "url":         "http://localhost:8001",
    "capabilities": ["confirm_order", "get_orders"],
    "skills": [
        {
            "name":        "confirm_order",
            "description": "Confirm and record a supplier order",
            "input_schema": {
                "type": "object",
                "properties": {
                    "product":       {"type": "string"},
                    "quantity":      {"type": "integer"},
                    "supplier":      {"type": "string"},
                    "unit_price":    {"type": "number"},
                    "total_price":   {"type": "number"},
                    "delivery_days": {"type": "integer"},
                    "score":         {"type": "number"}
                },
                "required": ["product", "quantity", "supplier", "unit_price", "total_price", "delivery_days"]
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "status":   {"type": "string"},
                    "order_id": {"type": "integer"},
                    "message":  {"type": "string"}
                }
            }
        },
        {
            "name":        "get_orders",
            "description": "Get all confirmed orders",
            "input_schema": {"type": "object", "properties": {}},
            "output_schema": {
                "type": "object",
                "properties": {"orders": {"type": "array"}}
            }
        }
    ],
    "authentication": {"type": "none"},
    "contact": "supplier-system"
}

# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(**DB_CONFIG)

def init_db():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id            SERIAL PRIMARY KEY,
            product       TEXT           NOT NULL,
            quantity      INTEGER        NOT NULL,
            supplier      TEXT           NOT NULL,
            unit_price    NUMERIC(10,2)  NOT NULL,
            total_price   NUMERIC(10,2)  NOT NULL,
            delivery_days INTEGER        NOT NULL,
            score         NUMERIC(6,4),
            status        TEXT           DEFAULT 'confirmed',
            created_at    TIMESTAMPTZ    DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    log.info("Orders table initialized in supplier_db")

def create_order(data: dict) -> dict:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        INSERT INTO orders
            (product, quantity, supplier, unit_price, total_price, delivery_days, score)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING *
    """, (
        data["product"],
        data["quantity"],
        data["supplier"],
        data["unit_price"],
        data["total_price"],
        data["delivery_days"],
        data.get("score")
    ))
    order = dict(cur.fetchone())
    conn.commit()
    cur.close()
    conn.close()
    return order

def fetch_orders() -> list:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM orders ORDER BY created_at DESC")
    orders = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return orders

# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(title="Order Agent")

@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)

@app.post("/a2a")
async def handle_a2a(request: Request):
    try:
        body = await request.json()
        task = body.get("task")

        log.info(f"A2A request: task={task}")

        if task == "confirm_order":
            required = ["product", "quantity", "supplier", "unit_price", "total_price", "delivery_days"]
            for field in required:
                if field not in body:
                    return JSONResponse(status_code=400, content={"status": "error", "message": f"Missing field: {field}"})

            order = create_order(body)
            log.info(f"Order confirmed: id={order['id']} supplier={body['supplier']} product={body['product']}")

            return JSONResponse(content={
                "status":   "success",
                "order_id": order["id"],
                "message":  f"Order #{order['id']} confirmed with {body['supplier']} for {body['quantity']}x {body['product']}"
            })

        elif task == "get_orders":
            orders = fetch_orders()
            return JSONResponse(content={
                "status": "success",
                "orders": [{**o, "created_at": str(o["created_at"]), "unit_price": str(o["unit_price"]), "total_price": str(o["total_price"]), "score": str(o["score"])} for o in orders]
            })

        else:
            return JSONResponse(status_code=400, content={"status": "error", "message": f"Unknown task: {task}"})

    except Exception as e:
        log.error(f"Error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/health")
async def health():
    return JSONResponse(content={"status": "ok"})

# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    log.info("Order Agent starting on http://localhost:8001")
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning")