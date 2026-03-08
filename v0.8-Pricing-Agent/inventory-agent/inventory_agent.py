"""
Inventory Agent — v0.8 Pricing Agent
Runs on port 8000.
Receives price update requests via A2A and updates pricing_db.
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
log = logging.getLogger("inventory-agent")

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()

DB_CONFIG = {
    "dbname":   os.getenv("DB_NAME",     "pricing_db"),
    "user":     os.getenv("DB_USER",     "adithyan"),
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "password": os.getenv("DB_PASSWORD", ""),
}

# ── Agent Card ────────────────────────────────────────────────────────────────

AGENT_CARD = {
    "name":        "Inventory Agent",
    "description": "Manages inventory and receives price updates from the Pricing Agent",
    "version":     "0.8.0",
    "url":         "http://localhost:8000",
    "capabilities": ["update_price", "get_inventory"],
    "skills": [
        {
            "name":        "update_price",
            "description": "Update the price of a product in the inventory DB",
            "input_schema": {
                "type": "object",
                "properties": {
                    "product":    {"type": "string", "description": "Product name"},
                    "new_price":  {"type": "number", "description": "New market price"},
                    "old_price":  {"type": "number", "description": "Previous DB price"},
                    "pct_change": {"type": "number", "description": "Percentage change"}
                },
                "required": ["product", "new_price"]
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "status":  {"type": "string"},
                    "product": {"type": "string"},
                    "price":   {"type": "number"}
                }
            }
        },
        {
            "name":        "get_inventory",
            "description": "Get all products with current prices",
            "input_schema": {"type": "object", "properties": {}},
            "output_schema": {
                "type": "object",
                "properties": {"products": {"type": "array"}}
            }
        }
    ],
    "authentication": {"type": "none"},
    "contact": "pricing-system"
}

# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(**DB_CONFIG)

def init_db():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id         SERIAL PRIMARY KEY,
            product    TEXT           NOT NULL UNIQUE,
            quantity   INTEGER        DEFAULT 0,
            price      NUMERIC(10, 2) DEFAULT 0.00,
            updated_at TIMESTAMPTZ    DEFAULT NOW()
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
    log.info("Inventory table initialized in pricing_db")

def update_price(product: str, new_price: float) -> dict | None:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "UPDATE inventory SET price = %s, updated_at = NOW() WHERE LOWER(product) = LOWER(%s) RETURNING *",
        (new_price, product)
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return dict(row) if row else None

def get_all_products() -> list:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM inventory ORDER BY product ASC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

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

        log.info(f"A2A request: task={task}")

        if task == "update_price":
            product   = body.get("product")
            new_price = body.get("new_price")
            old_price = body.get("old_price", "?")
            pct       = body.get("pct_change", "?")

            if not product or new_price is None:
                return JSONResponse(status_code=400, content={"status": "error", "message": "Missing product or new_price"})

            row = update_price(product, new_price)
            if not row:
                return JSONResponse(status_code=404, content={"status": "error", "message": f"Product '{product}' not found"})

            log.info(f"Price updated: {product} ${old_price} → ${new_price} ({pct:+.1f}%)" if isinstance(pct, float) else f"Price updated: {product} → ${new_price}")

            return JSONResponse(content={
                "status":  "success",
                "product": product,
                "price":   float(row["price"])
            })

        elif task == "get_inventory":
            products = get_all_products()
            return JSONResponse(content={
                "status":   "success",
                "products": [{**p, "price": str(p["price"]), "updated_at": str(p["updated_at"])} for p in products]
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
    log.info("Inventory Agent starting on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")