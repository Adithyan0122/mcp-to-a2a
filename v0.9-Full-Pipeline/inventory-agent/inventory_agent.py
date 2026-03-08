"""
Inventory Agent — v0.9 Full Pipeline
Runs on port 8000.
Receives price updates from Pricing Agent.
Handles low stock detection and supplier bidding when triggered by MCP server.
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
from concurrent.futures import ThreadPoolExecutor, as_completed
import uvicorn

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("inventory-agent")

load_dotenv()
DB_CONFIG = {
    "dbname":   os.getenv("DB_NAME",     "pipeline_v9_db"),
    "user":     os.getenv("DB_USER",     "adithyan"),
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "password": os.getenv("DB_PASSWORD", ""),
}
SUPPLIER_URLS         = [
    os.getenv("SUPPLIER_A_URL", "http://localhost:8011"),
    os.getenv("SUPPLIER_B_URL", "http://localhost:8012"),
    os.getenv("SUPPLIER_C_URL", "http://localhost:8013"),
]
ORDER_AGENT_URL        = os.getenv("ORDER_AGENT_URL",        "http://localhost:8001")
NOTIFICATION_AGENT_URL = os.getenv("NOTIFICATION_AGENT_URL", "http://localhost:8002")
RESTOCK_THRESHOLD      = int(os.getenv("RESTOCK_THRESHOLD",  15))
RESTOCK_QUANTITY       = int(os.getenv("RESTOCK_QUANTITY",   20))
DEADLINE_DAYS          = int(os.getenv("DEADLINE_DAYS",       6))

AGENT_CARD = {
    "name": "Inventory Agent", "version": "0.9.0",
    "url": "http://localhost:8000",
    "capabilities": ["update_price", "get_inventory", "check_and_restock"],
    "skills": [
        {"name": "update_price", "input_schema": {"type": "object",
            "properties": {"product": {"type": "string"}, "new_price": {"type": "number"},
            "old_price": {"type": "number"}, "pct_change": {"type": "number"}},
            "required": ["product", "new_price"]}},
        {"name": "get_inventory", "input_schema": {"type": "object", "properties": {}}},
        {"name": "check_and_restock", "input_schema": {"type": "object", "properties": {}}}
    ]
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
            price      NUMERIC(10,2)  DEFAULT 0.00,
            updated_at TIMESTAMPTZ    DEFAULT NOW()
        )
    """)
    cur.execute("SELECT COUNT(*) FROM inventory")
    if cur.fetchone()[0] == 0:
        cur.executemany("INSERT INTO inventory (product, quantity, price) VALUES (%s, %s, %s)", [
            ("Laptop",   10, 999.99), ("Mouse",    50,  29.99),
            ("Keyboard", 30,  79.99), ("Monitor",   8, 349.99), ("Webcam",   20,  89.99),
        ])
        log.info("Inventory seeded with 5 products")
    conn.commit()
    cur.close()
    conn.close()
    log.info("Inventory initialized in pipeline_v9_db")

def get_all_products() -> list:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM inventory ORDER BY quantity ASC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

def get_low_stock() -> list:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM inventory WHERE quantity < %s ORDER BY quantity ASC", (RESTOCK_THRESHOLD,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

def do_update_price(product: str, new_price: float) -> dict | None:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("UPDATE inventory SET price=%s, updated_at=NOW() WHERE LOWER(product)=LOWER(%s) RETURNING *",
        (new_price, product))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return dict(row) if row else None

# ── Bidding ───────────────────────────────────────────────────────────────────

_card_cache = {}

def discover(url: str) -> dict | None:
    if url in _card_cache:
        return _card_cache[url]
    try:
        card = httpx.get(f"{url}/.well-known/agent.json", timeout=5).json()
        _card_cache[url] = card
        return card
    except:
        return None

def bid_request(url: str, product: str, quantity: int, base_price: float) -> dict:
    start = time.time()
    try:
        discover(url)
        r = httpx.post(f"{url}/a2a", json={"task": "submit_bid", "product": product,
            "quantity": quantity, "base_price": base_price, "deadline_days": DEADLINE_DAYS}, timeout=5)
        result = r.json()
        result["latency_ms"] = round((time.time() - start) * 1000, 2)
        return result
    except Exception as e:
        return {"status": "error", "supplier": url, "message": str(e),
            "latency_ms": round((time.time() - start) * 1000, 2)}

def run_bidding(product: str, quantity: int, base_price: float) -> dict | None:
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(bid_request, url, product, quantity, base_price): url for url in SUPPLIER_URLS}
        bids = [f.result() for f in as_completed(futures)]

    accepted = [b for b in bids if b.get("status") == "accepted"]
    if not accepted:
        return None

    winner = min(accepted, key=lambda b: b.get("score", 999))
    log.info(f"Winner for {product}: {winner['supplier']} score={winner['score']} ${winner['unit_price']}")
    return winner

def notify_low_stock(product: str, quantity: int):
    try:
        httpx.post(f"{NOTIFICATION_AGENT_URL}/a2a", json={"task": "send_alert",
            "event_type": "low_stock", "product": product,
            "details": {"quantity": quantity, "threshold": RESTOCK_THRESHOLD}}, timeout=5)
    except Exception as e:
        log.warning(f"Low stock notify failed: {e}")

def confirm_order(winner: dict, product: str, quantity: int) -> dict:
    try:
        r = httpx.post(f"{ORDER_AGENT_URL}/a2a", json={"task": "confirm_order",
            "product": product, "quantity": quantity, "supplier": winner["supplier"],
            "unit_price": winner["unit_price"], "total_price": winner["total_price"],
            "delivery_days": winner["delivery_days"], "score": winner["score"]}, timeout=5)
        return r.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

def check_and_restock() -> dict:
    low_stock = get_low_stock()
    if not low_stock:
        return {"status": "ok", "message": "All products above threshold", "restocked": []}

    restocked = []
    for p in low_stock:
        log.info(f"Low stock: {p['product']} qty={p['quantity']} — running bidding")
        notify_low_stock(p["product"], p["quantity"])
        winner = run_bidding(p["product"], RESTOCK_QUANTITY, float(p["price"]))
        if winner:
            result = confirm_order(winner, p["product"], RESTOCK_QUANTITY)
            if result.get("status") == "success":
                restocked.append({"product": p["product"], "supplier": winner["supplier"],
                    "quantity": RESTOCK_QUANTITY, "order_id": result.get("order_id")})

    return {"status": "success", "restocked": restocked}

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

        if task == "update_price":
            product   = body.get("product")
            new_price = body.get("new_price")
            old_price = body.get("old_price", "?")
            pct       = body.get("pct_change", 0)
            if not product or new_price is None:
                return JSONResponse(status_code=400, content={"status": "error", "message": "Missing product or new_price"})
            row = do_update_price(product, new_price)
            if not row:
                return JSONResponse(status_code=404, content={"status": "error", "message": f"Product '{product}' not found"})
            log.info(f"Price updated: {product} ${old_price} → ${new_price} ({pct:+.1f}%)")
            return JSONResponse(content={"status": "success", "product": product, "price": float(row["price"])})

        elif task == "get_inventory":
            products = get_all_products()
            return JSONResponse(content={"status": "success",
                "products": [{**p, "price": str(p["price"]), "updated_at": str(p["updated_at"])} for p in products]})

        elif task == "check_and_restock":
            result = check_and_restock()
            return JSONResponse(content=result)

        else:
            return JSONResponse(status_code=400, content={"status": "error", "message": f"Unknown task: {task}"})

    except Exception as e:
        log.error(f"Error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/health")
async def health():
    return JSONResponse(content={"status": "ok"})

if __name__ == "__main__":
    init_db()
    log.info("Inventory Agent starting on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")