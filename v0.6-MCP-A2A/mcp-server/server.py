"""
MCP Inventory Server — v0.6 MCP + A2A
Runs as an MCP server connected to Claude Desktop.
Exposes inventory tools to Claude AND automatically triggers
A2A restock workflows when low stock is detected.

Flow:
Claude → MCP tool call → server.py → PostgreSQL
                                   ↘ A2A → Order Agent → Notification Agent → Email
"""

import json
import asyncio
import sys
import os
import time
import logging
import psycopg2
import psycopg2.extras
from psycopg2 import pool
import httpx
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
log = logging.getLogger("mcp-inventory")

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()

DB_CONFIG = {
    "dbname":   os.getenv("DB_NAME",     "pipeline_db"),
    "user":     os.getenv("DB_USER",     "adithyan"),
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "password": os.getenv("DB_PASSWORD", ""),
}

ORDER_AGENT_URL        = os.getenv("ORDER_AGENT_URL",        "http://localhost:8001")
NOTIFICATION_AGENT_URL = os.getenv("NOTIFICATION_AGENT_URL", "http://localhost:8002")
RESTOCK_THRESHOLD      = int(os.getenv("RESTOCK_THRESHOLD",  15))
RESTOCK_QUANTITY       = int(os.getenv("RESTOCK_QUANTITY",   20))

# ── Connection Pool ───────────────────────────────────────────────────────────

try:
    db_pool = psycopg2.pool.SimpleConnectionPool(minconn=1, maxconn=5, **DB_CONFIG)
    log.info("Database connection pool created")
except Exception as e:
    log.error(f"Failed to create connection pool: {e}")
    sys.exit(1)

def get_db():
    return db_pool.getconn()

def release_db(conn):
    db_pool.putconn(conn)

# ── Database Init ─────────────────────────────────────────────────────────────

def init_db():
    conn = get_db()
    try:
        cur = conn.cursor()
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
        log.info("Database initialized successfully")
    except Exception as e:
        log.error(f"Database init failed: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        release_db(conn)

# ── A2A Helpers ───────────────────────────────────────────────────────────────

_agent_card_cache = {}

def discover_agent(url: str) -> dict | None:
    if url in _agent_card_cache:
        return _agent_card_cache[url]
    try:
        response = httpx.get(f"{url}/.well-known/agent.json", timeout=5)
        card = response.json()
        _agent_card_cache[url] = card
        log.info(f"Discovered agent: {card.get('name')} at {url}")
        return card
    except Exception as e:
        log.warning(f"Could not discover agent at {url}: {e}")
        return None

def send_a2a(url: str, payload: dict) -> dict:
    try:
        response = httpx.post(f"{url}/a2a", json=payload, timeout=10)
        return response.json()
    except Exception as e:
        log.warning(f"A2A request failed to {url}: {e}")
        return {"status": "error", "message": str(e)}

def trigger_restock_pipeline(product: str, quantity: int, price: float) -> dict:
    """
    The bridge between MCP and A2A.
    Called automatically when a tool detects low stock.
    """
    log.info(f"Triggering A2A restock pipeline for {product} (qty={quantity})")

    results = {"product": product, "steps": []}

    # Step 1 — Send low stock alert
    notif_card = discover_agent(NOTIFICATION_AGENT_URL)
    if notif_card:
        alert_result = send_a2a(NOTIFICATION_AGENT_URL, {
            "task":       "send_alert",
            "event_type": "low_stock",
            "product":    product,
            "details":    {"quantity": quantity, "threshold": RESTOCK_THRESHOLD}
        })
        results["steps"].append({"step": "low_stock_alert", "status": alert_result.get("status")})
        log.info(f"Low stock alert: {alert_result.get('status')}")

    # Step 2 — Place restock order via A2A
    order_card = discover_agent(ORDER_AGENT_URL)
    if order_card:
        order_result = send_a2a(ORDER_AGENT_URL, {
            "task":     "place_order",
            "product":  product,
            "quantity": RESTOCK_QUANTITY
        })
        results["steps"].append({
            "step":     "restock_order",
            "status":   order_result.get("status"),
            "order_id": order_result.get("order", {}).get("id")
        })
        log.info(f"Restock order: {order_result.get('status')}")

    return results

# ── MCP Server ────────────────────────────────────────────────────────────────

app = Server("mcp-inventory-v6")

@app.list_tools()
async def list_tools():
    return [
        types.Tool(
            name="get_inventory",
            description="Get all products from inventory. Automatically triggers A2A restock for any low stock items found.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="read_stock",
            description="Read stock level for a specific product. Triggers A2A restock if stock is below threshold.",
            inputSchema={
                "type": "object",
                "properties": {
                    "product": {"type": "string", "description": "Product name to look up"}
                },
                "required": ["product"]
            }
        ),
        types.Tool(
            name="write_stock",
            description="Update the stock quantity of a product.",
            inputSchema={
                "type": "object",
                "properties": {
                    "product":  {"type": "string",  "description": "Product name"},
                    "quantity": {"type": "integer", "description": "New quantity"}
                },
                "required": ["product", "quantity"]
            }
        ),
        types.Tool(
            name="search_product",
            description="Search products by partial name or price range.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query":     {"type": "string", "description": "Partial product name"},
                    "min_price": {"type": "number", "description": "Minimum price (optional)"},
                    "max_price": {"type": "number", "description": "Maximum price (optional)"}
                },
                "required": []
            }
        ),
        types.Tool(
            name="update_price",
            description="Update the price of a product.",
            inputSchema={
                "type": "object",
                "properties": {
                    "product": {"type": "string", "description": "Product name"},
                    "price":   {"type": "number", "description": "New price"}
                },
                "required": ["product", "price"]
            }
        ),
    ]

# ── Tool Execution ────────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    start = time.time()
    conn  = None
    pipeline_results = []

    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        if name == "get_inventory":
            cur.execute("SELECT * FROM inventory ORDER BY quantity ASC")
            rows   = [dict(r) for r in cur.fetchall()]
            result = rows

            # Auto-trigger A2A restock for any low stock products
            low_stock = [r for r in rows if r["quantity"] < RESTOCK_THRESHOLD]
            if low_stock:
                log.info(f"Auto-triggering restock for {len(low_stock)} low stock product(s)")
                for product in low_stock:
                    pipeline = trigger_restock_pipeline(
                        product["product"],
                        product["quantity"],
                        float(product["price"])
                    )
                    pipeline_results.append(pipeline)

        elif name == "read_stock":
            product = arguments.get("product", "").strip()
            if not product:
                raise ValueError("'product' is required")
            cur.execute(
                "SELECT * FROM inventory WHERE LOWER(product) = LOWER(%s)",
                (product,)
            )
            row = cur.fetchone()
            if not row:
                result = {"error": f"Product '{product}' not found"}
            else:
                result = dict(row)
                # Auto-trigger A2A restock if low stock
                if result["quantity"] < RESTOCK_THRESHOLD:
                    log.info(f"Low stock detected for {product} — triggering A2A pipeline")
                    pipeline = trigger_restock_pipeline(
                        result["product"],
                        result["quantity"],
                        float(result["price"])
                    )
                    pipeline_results.append(pipeline)

        elif name == "write_stock":
            product  = arguments.get("product", "").strip()
            quantity = arguments.get("quantity")
            if not product:
                raise ValueError("'product' is required")
            if quantity is None or quantity < 0:
                raise ValueError("'quantity' must be non-negative")
            cur.execute(
                "UPDATE inventory SET quantity = %s WHERE LOWER(product) = LOWER(%s) RETURNING *",
                (quantity, product)
            )
            row = cur.fetchone()
            conn.commit()
            result = dict(row) if row else {"error": f"Product '{product}' not found"}

        elif name == "search_product":
            query     = arguments.get("query", "")
            min_price = arguments.get("min_price")
            max_price = arguments.get("max_price")
            sql       = "SELECT * FROM inventory WHERE product ILIKE %s"
            params    = [f"%{query}%"]
            if min_price is not None:
                sql += " AND price >= %s"
                params.append(min_price)
            if max_price is not None:
                sql += " AND price <= %s"
                params.append(max_price)
            cur.execute(sql, params)
            result = [dict(r) for r in cur.fetchall()]

        elif name == "update_price":
            product = arguments.get("product", "").strip()
            price   = arguments.get("price")
            if not product:
                raise ValueError("'product' is required")
            if price is None or price < 0:
                raise ValueError("'price' must be non-negative")
            cur.execute(
                "UPDATE inventory SET price = %s WHERE LOWER(product) = LOWER(%s) RETURNING *",
                (price, product)
            )
            row = cur.fetchone()
            conn.commit()
            result = dict(row) if row else {"error": f"Product '{product}' not found"}

        else:
            raise ValueError(f"Unknown tool: {name}")

        cur.close()

    except ValueError as e:
        log.warning(f"[{name}] Validation error: {e}")
        result = {"error": str(e)}
        if conn:
            conn.rollback()
    except psycopg2.Error as e:
        log.error(f"[{name}] Database error: {e}")
        result = {"error": f"Database error: {str(e)}"}
        if conn:
            conn.rollback()
    except Exception as e:
        log.error(f"[{name}] Unexpected error: {e}")
        result = {"error": str(e)}
        if conn:
            conn.rollback()
    finally:
        if conn:
            release_db(conn)

    latency_ms = round((time.time() - start) * 1000, 2)
    log.info(f"[{name}] completed in {latency_ms}ms")

    payload = {
        "result":     result,
        "latency_ms": latency_ms,
    }
    if pipeline_results:
        payload["a2a_pipeline"] = pipeline_results

    return [types.TextContent(type="text", text=json.dumps(payload, indent=2, default=str))]

# ── Entry Point ───────────────────────────────────────────────────────────────

async def main():
    log.info("MCP Inventory Server v0.6 starting...")
    log.info(f"Order Agent:        {ORDER_AGENT_URL}")
    log.info(f"Notification Agent: {NOTIFICATION_AGENT_URL}")
    log.info(f"Restock threshold:  {RESTOCK_THRESHOLD} units")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    init_db()
    asyncio.run(main())