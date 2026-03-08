"""
Order Agent — v1.0
Runs on port 8001.
Confirms winning supplier bids, records orders, notifies via Notification Agent.
Enhanced with circuit breakers, tracing, and memory.
"""

import logging
import sys
import os
import time
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.config import DB_CONFIG, NOTIFICATION_AGENT_URL, FINANCE_AGENT_URL
from shared.tracing import traced_a2a_call
from shared.circuit_breaker import get_breaker
from shared.health import build_health_response, check_db_connection
from shared.memory import MemoryClient

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("order-agent")

load_dotenv()

memory = MemoryClient()
notify_cb = get_breaker("order->notification-agent", failure_threshold=5, timeout=30)
finance_cb = get_breaker("order->finance-agent", failure_threshold=3, timeout=30)

started_at = time.time()

AGENT_CARD = {
    "name": "Order Agent", "version": "1.0.0",
    "url": "http://localhost:8001",
    "capabilities": ["confirm_order", "get_orders"],
    "skills": [
        {"name": "confirm_order", "input_schema": {"type": "object",
            "properties": {"product": {"type": "string"}, "quantity": {"type": "integer"},
            "supplier": {"type": "string"}, "unit_price": {"type": "number"},
            "total_price": {"type": "number"}, "delivery_days": {"type": "integer"},
            "score": {"type": "number"}},
            "required": ["product", "quantity", "supplier", "unit_price", "total_price", "delivery_days"]}},
        {"name": "get_orders", "input_schema": {"type": "object", "properties": {}}}
    ]
}

def get_db():
    return psycopg2.connect(**DB_CONFIG)

def init_db():
    conn = get_db()
    cur = conn.cursor()
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
    log.info("Orders table initialized")

def create_order(data: dict) -> dict:
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        INSERT INTO orders (product, quantity, supplier, unit_price, total_price, delivery_days, score)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *
    """, (data["product"], data["quantity"], data["supplier"],
          data["unit_price"], data["total_price"], data["delivery_days"], data.get("score")))
    order = dict(cur.fetchone())
    conn.commit()
    cur.close()
    conn.close()
    return order

def fetch_orders() -> list:
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM orders ORDER BY created_at DESC")
    orders = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return orders

def notify(product: str, details: dict):
    try:
        notify_cb.call(traced_a2a_call, NOTIFICATION_AGENT_URL,
            {"task": "send_alert", "event_type": "order_placed",
             "product": product, "details": details})
        log.info(f"Notification sent for {product}")
    except Exception as e:
        log.warning(f"Notification failed: {e}")

def record_budget_transaction(order_id: int, amount: float):
    """Notify Finance Agent of the confirmed spend."""
    try:
        finance_cb.call(traced_a2a_call, FINANCE_AGENT_URL,
            {"task": "record_spend", "order_id": order_id, "amount": amount})
    except Exception as e:
        log.warning(f"Budget recording failed: {e}")

app = FastAPI(title="Order Agent v1.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"])

@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)

@app.post("/a2a")
async def handle_a2a(request: Request):
    try:
        body = await request.json()
        task = body.get("task")

        if task == "confirm_order":
            required = ["product", "quantity", "supplier", "unit_price", "total_price", "delivery_days"]
            for f in required:
                if f not in body:
                    return JSONResponse(status_code=400,
                        content={"status": "error", "message": f"Missing: {f}"})
            order = create_order(body)
            log.info(f"Order #{order['id']} confirmed: {body['supplier']} — {body['product']}")

            # Record budget transaction
            record_budget_transaction(order["id"], float(body["total_price"]))

            # Send notification
            notify(body["product"], {
                "order_id": order["id"], "supplier": body["supplier"],
                "quantity": body["quantity"], "unit_price": body["unit_price"],
                "total_price": body["total_price"], "delivery_days": body["delivery_days"],
                "llm_reasoning": body.get("llm_reasoning", ""),
            })

            return JSONResponse(content={
                "status": "success", "order_id": order["id"],
                "message": f"Order #{order['id']} confirmed with {body['supplier']} "
                           f"for {body['quantity']}x {body['product']}"
            })

        elif task == "get_orders":
            orders = fetch_orders()
            return JSONResponse(content={"status": "success",
                "orders": [{**o, "created_at": str(o["created_at"]),
                "unit_price": str(o["unit_price"]), "total_price": str(o["total_price"]),
                "score": str(o["score"])} for o in orders]})

        else:
            return JSONResponse(status_code=400,
                content={"status": "error", "message": f"Unknown task: {task}"})
    except Exception as e:
        log.error(f"Error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/health")
async def health():
    db_ok = check_db_connection(DB_CONFIG)
    deps = {
        "notification-agent": notify_cb.get_status(),
        "finance-agent": finance_cb.get_status(),
    }
    return JSONResponse(content=build_health_response(
        "Order Agent", "1.0.0", db_connected=db_ok, dependencies=deps
    ))

if __name__ == "__main__":
    init_db()
    log.info("Order Agent v1.0 starting on http://localhost:8001")
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning")
