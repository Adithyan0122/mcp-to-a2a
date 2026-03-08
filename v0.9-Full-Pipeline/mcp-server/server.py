"""
MCP Server — v0.9 Full Pipeline
The entry point for Claude Desktop.
Exposes 5 tools to Claude. Each tool triggers the full agent pipeline behind the scenes.

Full flow when Claude calls get_inventory:
  1. Sync prices via Pricing Agent (A2A)
  2. Read inventory from DB
  3. Detect low stock
  4. Trigger supplier bidding via Inventory Agent (A2A)
  5. Order Agent confirms winner (A2A)
  6. Notification Agent sends emails (A2A)
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

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("mcp-server-v9")

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()

DB_CONFIG = {
    "dbname":   os.getenv("DB_NAME",     "pipeline_v9_db"),
    "user":     os.getenv("DB_USER",     "adithyan"),
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "password": os.getenv("DB_PASSWORD", ""),
}

MARKET_API_URL         = os.getenv("MARKET_API_URL",         "http://localhost:9000")
PRICING_AGENT_URL      = os.getenv("PRICING_AGENT_URL",      "http://localhost:9001")
INVENTORY_AGENT_URL    = os.getenv("INVENTORY_AGENT_URL",    "http://localhost:8000")
ORDER_AGENT_URL        = os.getenv("ORDER_AGENT_URL",        "http://localhost:8001")
NOTIFICATION_AGENT_URL = os.getenv("NOTIFICATION_AGENT_URL", "http://localhost:8002")
RESTOCK_THRESHOLD      = int(os.getenv("RESTOCK_THRESHOLD",  15))

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

# ── A2A Helpers ───────────────────────────────────────────────────────────────

def call_a2a(url: str, payload: dict, timeout: int = 10) -> tuple[dict, float]:
    start = time.time()
    try:
        r       = httpx.post(f"{url}/a2a", json=payload, timeout=timeout)
        latency = round((time.time() - start) * 1000, 2)
        return r.json(), latency
    except Exception as e:
        latency = round((time.time() - start) * 1000, 2)
        log.warning(f"A2A call to {url} failed: {e}")
        return {"status": "error", "message": str(e)}, latency

# ── MCP Server ────────────────────────────────────────────────────────────────

app = Server("mcp-full-pipeline-v9")

@app.list_tools()
async def list_tools():
    return [
        types.Tool(
            name="get_inventory",
            description=(
                "Get full inventory with live market prices. "
                "Automatically syncs prices from the market, detects low stock, "
                "runs supplier bidding, places restock orders and sends email alerts. "
                "This triggers the entire supply chain pipeline."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="sync_prices",
            description="Manually trigger a price sync between the market API and inventory DB.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="check_stock",
            description="Check current stock levels without triggering any pipeline actions.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="get_orders",
            description="Get all confirmed restock orders placed by the Order Agent.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="get_market_prices",
            description="Get current live market prices from the Market API.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    pipeline_start = time.time()
    timings        = {}
    conn           = None

    try:
        # ── get_inventory — THE FULL PIPELINE ────────────────────────────────
        if name == "get_inventory":
            log.info("=" * 60)
            log.info("Full pipeline triggered via MCP get_inventory")

            # Step 1 — Sync prices
            log.info("Step 1: Syncing prices via Pricing Agent...")
            t0 = time.time()
            sync_result, sync_ms = call_a2a(PRICING_AGENT_URL, {"task": "sync_prices"})
            timings["price_sync_ms"] = sync_ms
            updates = sync_result.get("updates", [])
            log.info(f"  Price sync: {len(updates)} update(s) in {sync_ms}ms")

            # Step 2 — Read inventory from DB
            log.info("Step 2: Reading inventory from DB...")
            conn      = get_db()
            cur       = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM inventory ORDER BY quantity ASC")
            products  = [dict(r) for r in cur.fetchall()]
            cur.close()
            release_db(conn)
            conn = None
            low_stock = [p for p in products if p["quantity"] < RESTOCK_THRESHOLD]
            log.info(f"  {len(products)} products, {len(low_stock)} low stock")

            # Step 3 — Trigger restock if needed
            restock_result = None
            if low_stock:
                log.info(f"Step 3: Triggering restock for {len(low_stock)} product(s)...")
                restock_result, restock_ms = call_a2a(
                    INVENTORY_AGENT_URL,
                    {"task": "check_and_restock"},
                    timeout=60
                )
                timings["restock_ms"] = restock_ms
                log.info(f"  Restock: {len(restock_result.get('restocked', []))} order(s) in {restock_ms}ms")
            else:
                log.info("Step 3: No restock needed")

            total_ms = round((time.time() - pipeline_start) * 1000, 2)
            timings["total_ms"] = total_ms
            log.info(f"Full pipeline complete in {total_ms}ms")
            log.info("=" * 60)

            result = {
                "products":      [{**p, "price": str(p["price"]), "updated_at": str(p["updated_at"])} for p in products],
                "low_stock":     [p["product"] for p in low_stock],
                "price_updates": updates,
                "restock":       restock_result,
                "timings":       timings
            }

        # ── sync_prices ───────────────────────────────────────────────────────
        elif name == "sync_prices":
            sync_result, sync_ms = call_a2a(PRICING_AGENT_URL, {"task": "sync_prices"})
            result = {**sync_result, "latency_ms": sync_ms}

        # ── check_stock ───────────────────────────────────────────────────────
        elif name == "check_stock":
            conn     = get_db()
            cur      = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM inventory ORDER BY quantity ASC")
            products = [dict(r) for r in cur.fetchall()]
            cur.close()
            release_db(conn)
            conn = None
            result = {
                "products":  [{**p, "price": str(p["price"]), "updated_at": str(p["updated_at"])} for p in products],
                "low_stock": [p["product"] for p in products if p["quantity"] < RESTOCK_THRESHOLD],
                "total":     len(products)
            }

        # ── get_orders ────────────────────────────────────────────────────────
        elif name == "get_orders":
            orders_result, ms = call_a2a(ORDER_AGENT_URL, {"task": "get_orders"})
            result = {**orders_result, "latency_ms": ms}

        # ── get_market_prices ─────────────────────────────────────────────────
        elif name == "get_market_prices":
            start = time.time()
            r     = httpx.get(f"{MARKET_API_URL}/prices", timeout=5)
            ms    = round((time.time() - start) * 1000, 2)
            result = {**r.json(), "latency_ms": ms}

        else:
            result = {"error": f"Unknown tool: {name}"}

    except Exception as e:
        log.error(f"[{name}] Error: {e}")
        result = {"error": str(e)}
        if conn:
            release_db(conn)

    total_ms = round((time.time() - pipeline_start) * 1000, 2)
    log.info(f"[{name}] completed in {total_ms}ms")

    return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

# ── Entry Point ───────────────────────────────────────────────────────────────

async def main():
    log.info("MCP Full Pipeline Server v0.9 starting...")
    log.info(f"Market API:         {MARKET_API_URL}")
    log.info(f"Pricing Agent:      {PRICING_AGENT_URL}")
    log.info(f"Inventory Agent:    {INVENTORY_AGENT_URL}")
    log.info(f"Order Agent:        {ORDER_AGENT_URL}")
    log.info(f"Notification Agent: {NOTIFICATION_AGENT_URL}")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())